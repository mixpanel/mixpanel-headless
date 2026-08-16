# B6 batch notes

**Status**: CLOSED — gate passed 2026-08-16 (this commit). Conformance
**3,230 PASS / 0 FAIL / 21 UNPORTED** @ corpus pin `70c904dc598d`
(gate delta +354 exactly: the 353 `workspace.<B6-member>` vectors + the
P3-1 † carried dagger vector; report
`context/phase3/reports/2026-08-16-b6-gate.json`). Finalized by the
B6-GATE task per P3-2 step (e) item 5.

Shard notes: `B6-W1-notes.md` … `B6-W8-notes.md` · `B6-BIND-notes.md`.
Reviews: `../design/b6-review-fidelity.md` ·
`../design/b6-review-assertions.md`. Arbiter resolution:
`../design/b6-review-resolution.md` (all 7 findings confirmed + applied,
GO; TS commit `4ae898f`).

## Gate record (B6-GATE, fable, 2026-08-16)

TS gate commits (main): `1aab800` (flip + checkpoint + probe
re-anchor), `6d5f666` (`pythonFloatCoerce` ledger closure + KeyError
twin fold), `db8e079` (throwaway cleanup). Python gate commit: this
one.

- [x] (1) **Flip, one commit with the checkpoint** (playbook P3-5 §4
  B6-gate rule / b6-packets.md §12.1): the 44 B5 exact-name
  `workspace.<member>` → `done` entries, the
  `workspace.list_bookmarks_v2` → `pending` override, and the
  `workspace.` → `pending` row all COLLAPSED to the single entry
  **`workspace.` → `done`** (longest-prefix keeps every B5 name's state
  equivalent; the override removal is the B5 §7.1 forward note landing
  here). Doc comment rewritten; batch-status unit suite updated to the
  collapsed-table lock (exact-name entries asserted ABSENT, single
  `workspace.` prefix asserted, representative B5+B6 names resolve
  `done`). **Standing collision assertion re-run MECHANICALLY over the
  FINAL table** (esbuild-bundled scan through the real `batchStatusFor`
  + `loadCorpus`; 3,251 vectors, 424 distinct api names measured+setup):

  ```json
  {
    "pendingNames": [
      {"api": "oauth_flow.refresh_tokens", "occurrences": 7,
       "doneEntryStartsWithHits": []},
      {"api": "region_probe.probe_region", "occurrences": 14,
       "doneEntryStartsWithHits": []}
    ],
    "workspacePendingCount": 0,
    "tableEntries": 20
  }
  ```

  Exactly the b6-packets §12.1 expectation: after this gate the ONLY
  pending prefixes are `region_probe.` and `oauth_flow.`; zero pending
  names prefix-match any `done` entry; no `workspace.*` name remains
  pending.
- [x] (1b) **UNPORTED-probe re-anchor** (§12.5): the measured-api probe
  (`runner.test.ts`) and both `oracle-protocol.test.ts` exemplars were
  re-anchored to `region_probe.probe_region` EARLY at B6-BIND
  (disclosed in the assertions review §1); the gate re-anchored the
  remaining `workspace.me` SETUP-gating probe (`runner.test.ts:147+`)
  to the same name. Pattern retires at the B8 gate (b6-packets §12.5).
- [x] (2) **Conformance checkpoint**: 3,251 vectors — **3,230 PASS /
  0 FAIL / 21 UNPORTED** @ `70c904dc598d`, byte-equal to the §12.2
  expectation and to the pre-flip BIND counts (every bound name already
  replayed; the flip is purely the straggler ratchet). Attribution
  (mechanical, measured-api grouping of gated vectors): 21 UNPORTED =
  **14 `region_probe.probe_region` + 7 `oauth_flow.refresh_tokens`**;
  +354 = 353 `workspace.<B6-member>` + 1 dagger
  (`auth/api_client.resolve_workspace_id/test_workspace_resolution-testfacaderesolverwiring-test_resolves_from_me_cache_without_public_call`
  — its `workspace.me` setup now executes through the real facade
  binding; verified no longer setup-gated). Report archived:
  `context/phase3/reports/2026-08-16-b6-gate.json`.
- [x] (3) **Oracle probes**: the B6 batch's own new-name set is EMPTY
  as designed (§11.5 — all 154 BIND names are wire-kind; wire names
  have no oracle call surface, `oracle_py/server.py:414-418`). The
  GATE itself registered ONE new builder-kind api
  (`compat.python_float_coerce`, ledger item below): probed via a full
  fuzz-family run against BOTH bridges — **514 examples (500 + 14 R10.9
  edges) / 0 skips / 0 divergences**, i.e. both bridges answer call
  DATA for the name (non-"unknown api").
- [x] (4) **Differential full-suite regression** (P3-7): cumulative
  surface now **55 families** (54 prior + `python_float_coerce`).
  SEVEN seeds — fresh **628997442** + replays of EVERY prior gate seed:
  **3343231** (B2 fresh), **28631260** (B0), **52794688** (B0),
  **40075993** (B3 fresh), **53062695** (B4 fresh), **47824574** (B5
  fresh). A first pass over the 54-family surface (before the gate's
  compat addition) was clean on all seven at 27,577/0/0. The 55-family
  pass then caught **ONE REAL RIG-OBSERVABLE BUG** (seed 3343231,
  `cohort_family`, shrunken repro
  `types.CohortCriteria.has_property {operator:"junk"}`): py
  `KeyError` vs ts `KeyError2` — TWO same-named `KeyError` classes
  existed (`types/query-params/cohort.ts`'s module-local mirror from
  the P2-9 fix + the canonical `query/python-builtins.ts` twin), and
  the gate's compat import re-ordered the esbuild oracle bundle so the
  cohort copy got renamed `KeyError2` (the bridge compares
  `constructor.name`, oracle-protocol §4.1). Never previously
  observable: the python-builtins twin is thrown only by B5 discovery
  parsers (wire — no oracle surface), so bundle rename order was
  invisible until the order flipped. FIXED per python-builtins' own
  R10.4 watch note ("if a third appears, fold the cohort copy"): the
  module-local duplicate DELETED, `cohort.ts` imports the canonical
  twin (import-free leaf, no cycle); fix verified by a direct oracle
  probe of the repro input (`class: "KeyError"`) and the repro file
  deleted with the fix (B5-gate precedent). ALL SEVEN seeds then
  re-run over the final tree: **28,091 examples / 0 skips /
  0 divergences** per seed, exit 0, status `ok`, no repros written.
  Raw JSONs:
  `conformance/differential/oracle/2026-08-16-b6-gate-seed{628997442,3343231,28631260,52794688,40075993,53062695,47824574}.json`;
  RUN.md appended. `repros/` back to exactly the two RESOLVED P2-9
  triage records.
- [x] (5) **Referees (a)+(b) — REQUIRED at this gate** (P3-7; §12.4).
  W3 shard-notes check first: `create_bookmark`/`update_bookmark`
  validate/pass through ALREADY-BUILT params (construction stayed
  B3/B5) — **no new bookmark-emitting surface, no feed-slot change**
  (the feed already carries `workspace.build_params` from the B5
  extension). (a) ajv runner feed (`npm run referee:bookmark`): 213
  fed — **208 ACCEPT + the 5 pinned expected-and-disclosed dataGroupId
  REJECTs** (4 standing B3 clause-level pins + the B5 sections-level
  pin), pin-exactness asserted by the test itself; green. (b)
  bookmark_parser round-trip: handoff regenerated — **byte-identical,
  314 entries**; selftest controls passed for BOTH oracles before the
  batches; structural **314/314 ACCEPT** (jsonschema 4.26.0); deep
  **123 ACCEPT / 2 REJECT / 189 SKIP_NON_INSIGHTS** (voluptuous
  0.16.0) — the 2 are the standing frequency-filter true positives
  (expected-and-disclosed, exit 1 by design). **No NEW reject on
  either referee — non-blocking.**
- [x] (6) **Deferral audit** — every B5 §8 outbound item verified ON
  DISK: `use()`/`close()`/`[Symbol.asyncDispose]` live
  (`workspace.ts:1226/:1309/:1319`; no `UNPORTED_MEMBER` stubs remain);
  `workspace.me` bound through the real facade + dagger closed (item 2
  above); `stream_events`/`stream_profiles`/`api` veneer decision
  closed as W1-D3 (`yield*` veneers `:3263/:3279` + `get api()`
  `:3126`); `TestDiscoveryCacheAcrossUse` translated
  (`facade-scoping.test.ts:86`); the `list_bookmarks_v2` override
  removal landed in this gate's flip; UNPORTED-probe re-anchor done
  (item 1b). b6-packets §13 inbound residue verified via the
  assertions review §1: `response-validation.ts` TODO re-scoped in
  place with an R10.3 disclosure + corpus-lock cite (W3);
  Discrepancy #10 re-examination recorded in `B6-W3-notes.md` (ruling
  stands). **B5-notes.md outbound ledger item 5 (`pythonFloatCoerce`,
  owner = B6 gate) EXECUTED at this gate** — record below.
  `throwaway/b6-w{1..8}/` removed (RUN records preserved in the eight
  shard notes files).
- [x] Checks: `npm run check` green (TS); `just check` green (Python).

## Gate-executed ledger item: `pythonFloatCoerce` (R11.7 straggler, B5-notes ledger item 5)

The ASR-F6b remediation (B5-ARB) fixed the
`FunnelQueryResult.overall_conversion_rate` STRING arm only; the
non-string ladder (`floatValue(x) ?? 0.0`) still returned `0.0` where
CPython `float(x)` raises `TypeError` (None/list/dict) and `0.0` for
`True` where CPython returns `1.0`. Closed at this gate as the ledger
prescribed — a B0-style both-repo compat addition, red-first:

- **CPython probe record (3.14.6, 2026-08-16)**: `float(True)` → `1.0`;
  `float(False)` → `0.0`; `float(None)` → `TypeError "float() argument
  must be a string or a real number, not 'NoneType'"` (list/dict/tuple
  spell `'list'`/`'dict'`/`'tuple'`); `float(10**400)` →
  `OverflowError "int too large to convert to float"` (both signs);
  `float("1e400")` → `inf` (string parse saturates; int conversion
  raises).
- **TS**: `packages/core/src/compat/python-float-coerce.ts`
  (`pythonFloatCoerce` — number/bool/bigint/string/spelling-wrapper/
  None/list/dict ladder; string arm delegates to `pythonFloat` R10.8;
  TypeError twins native; OverflowError twin imported from the
  import-free `query/python-builtins.ts` leaf), exported from
  `compat/index.ts`; the library site now returns
  `pythonFloatCoerce(value)`. Red-first: 4 site tests
  (`transform-raise-fidelity.test.ts` B6-GATE describe) + the compat
  suite (`python-float-coerce.test.ts`) written first and confirmed
  red (4 failed + import failure), then green post-implementation.
- **Rig**: binding `compat.python_float_coerce` registered beside
  `compat.python_float` (same `guardCompat` +
  `encodePythonFloatResult` sentinel encode); `authored-apis.json`
  entry + `api-map.gen.ts` regenerated. Python mirror
  `pycompat_ref.python_float_coerce` (same coded-ValueError +
  non-finite `repr` sentinel translations as `python_float`;
  TypeError/OverflowError propagate bare per oracle-protocol §4.1);
  registry `_gate_entries()` + `test_registry` required-set +
  `test_fuzz_harness` `_PHASE3_NAMES` extended.
- **Fuzz family** (`strategies.py::_PYTHON_FLOAT_COERCE`, in
  `PHASE3_TARGETS`): payload-value universe = the `python_float`
  grammar-adjacent string core + safe-range ints + finite floats +
  bools + None + small lists/dicts; 14 R10.9 edge calls (integral
  float, fractional float, True, None, empty list, empty string,
  non-BMP string, dict, int, −0.0, overflow sentinel strings, 2^53−1
  boundary). **Domain notes (documented omissions)**: unsafe ints are
  transport-barred (R4.5 codec policy), so the `float(10**400)`
  OverflowError branch is locked TS-side only
  (`python-float-coerce.test.ts` huge-int-spelling + bigint arms) —
  the Discrepancy #6/#7 class reasoning applies (in the LIBRARY path a
  huge integer token collapses at `JsonNumber.toNumber()` before the
  ladder, so TS returns ±Infinity where CPython raises OverflowError:
  same unrepresentable-big-int class, disclosed here); non-finite
  INPUT floats excluded (identity arm; the sentinel OUTPUT path is
  exercised via the `"1e400"`/`"-iNf"` string edges;
  `python_float_str` precedent).
- Family run: 514/514 both bridges, 0 divergences (item 3 above); all
  seven full-suite seeds re-run AFTER the addition (item 4).

## Tier observations (P3-2e item 5; opus findings attribution)

B6 ran the two-tier program at its largest member count (158 members,
8 opus W-shards; packet/BIND/reviews/arbiter/gate on fable):

1. **Zero vector failures at BIND** (353/353 + dagger on the first
   full replay) — opus first-attempt quality on facade delegation code
   was high, consistent with B5 observation 4; zero P3-3 escalations.
2. **The risk-register #3 pattern materialized as PREDICTED but in a
   new shape**: both MAJORs were cross-shard COVERAGE drops, not
   assertion weakening inside translated tests — (a) 26
   `crud-edge.test.ts` todos left unconverted by W4–W8 (a dropped
   hand-off protocol, booked 4/6/4/8/4 against those shards); (b)
   17 `TestLiveQueries`/`TestDiscovery` translations dropped behind a
   whole-class header claim. The R10.2 per-file diff at review caught
   both; B7–B9's doubled review inherits this watch item.
3. **Watchlist #13 hit the R10.4 threshold and the amendment was
   FILED** (arbiter finding D): `isPythonDict` moved to the leaf
   `compat/python-dict.ts` as the canonical home; standing rule "one
   named guard per discrimination semantics, import-only". The B6-BIND
   local twin was the 6th recurrence; greps confirm zero twins remain.
4. **`pytest.raises(Class, match=…)` class-drop tally now stands at
   two batch recurrences** (B5 ~55 sites, B6 6 sites — arbiter finding
   C): ONE more batch recurrence triggers a translation-prompt
   amendment per the standing tally.
5. Both gate-time work items were rig/fable-owned surfaces (the
   batch-status collapse mechanics, the compat ledger closure) —
   consistent with the "judge stronger than judged" allocation; no
   downward-tier leakage.

## Discrepancies & escalations

- **No new discrepancy filed at B6.** Discrepancy #10's named
  re-examination happened at W3 (ruling stands; fuzz exclusion kept).
  The gate's `pythonFloatCoerce` big-int disclosure above is an
  instance of the standing #6/#7 unrepresentable-big-int class, not a
  new entry (per the #12 precedent it is recorded at the strategy site
  and here, inside the existing ruling).
- Escalations: **none** (no module task missed done-criteria; the one
  R10.4 threshold crossing — watchlist #13 — was amended at the
  arbiter step, not escalated).
- Open R10.7 items carried forward (unchanged): frequency-filter
  clause shape (2 deep-referee REJECTs) + dataGroupId int threading
  (5 ajv pins) — both await a Python-first fix + re-extraction cycle;
  neither blocks Phase-3 batches.
- Standing posture for B7/B8: after this gate the only pending
  prefixes are `region_probe.` (14 vectors) and `oauth_flow.` (7);
  auth batches run fable with DOUBLED review (P3-3); the
  UNPORTED-probe anchors now sit on `region_probe.probe_region` and
  retire at the B8 gate; outbound deferral ledger for B7/B8 is
  b6-packets.md §13 (resolver seams, `persistActive`, on-disk
  `MeCacheStore`, `readFile` seam, the B7/B8 test-file splits).
