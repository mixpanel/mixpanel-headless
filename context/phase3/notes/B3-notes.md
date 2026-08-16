# B3 batch notes — builders (K1–K4) · batch gate record

**Status**: GATE CLOSED (2026-08-15) — all P3-2e steps green; one rig-strategy remediation en route (see §Gate working log item 4)
**Model**: gate task fable (P3-3); module tiering observations in §Tier attribution
**Date**: 2026-08-15
**Spec**: playbook v1.1 §P3-2e; packet `b3-packets.md` §Batch-status / flip / gate

## Module-task ledger (from shard notes; see per-shard files)

- K1 (`B3-K1-notes.md`): bookmark_schema remaining slice + bookmark_enums parity — opus; TS `0a68942`; 114 Layer-3 tests; harness 15,389 compared / 1 disclosed divergence (→ Discrepancy #10)
- K2 (`B3-K2-notes.md`): bookmark_builders whole file — opus; TS `5024bb4`; 166 Layer-3 tests; harness 36,250 / 0
- K3 (`B3-K3-notes.md`): segfilter + expressions + transforms — opus; TS `755e9a1`; 142 Layer-3 tests; harness 12,970 / 0
- K4 (`B3-K4-notes.md`): user_builders selector path — opus; TS `9add8c4`; 88 Layer-3 tests; doubled-budget harness 17,655 / 0
- BIND (`B3-BIND-notes.md`): 17 apis bound + oracle-registered — fable; TS `45a06cf`, py `70c904d` + re-pin `d89f2a8`; 299/299 PASS at bind; fuzz seed 64091337: 9,395 ex / 0 div
- Review pair: `769eb04` (assertions lens, GO w/ K1-D1 open) + `8e72163` (fidelity lens, NO-GO w/ F1 MAJOR); arbiter `d7fa205` / TS fix `7de21a8` — all 6 findings applied, **GO for gate**

## Gate checklist (P3-2e)

- [x] (1) batch-status flip: `bookmark_builders.` `segfilter.` `user_builders.` `expressions.` `transforms.` → done + ADD `bookmark_schema.` → done; header comment pending-list updated; no-prefix-collision assertion run (14/14 captured names B3-owned, zero pending captures)
- [x] (2) conformance checkpoint: **3,251 = 1,528 PASS / 0 FAIL / 1,723 UNPORTED** @ corpus 70c904d (the playbook's b5c1369 pin superseded by the B3-BIND re-pin, P3-7 trigger 1); dagger verified (zero `call.setup[]` on all 299, zero foreign B3 setups — gate delta = raw 299); report archived `context/phase3/reports/2026-08-15-b3-gate.json`
- [x] (3) oracle probes: **17/17** B3 apis answer call DATA on BOTH bridges, canonical outcomes pairwise equal (both @ 70c904d, protocol 1.1)
- [x] (4) differential regression: fresh seed **40075993** + prior-gate replays **3343231 / 28631260 / 52794688** — attempt 1 BLOCKED by a rig-strategy transport crash (fixed red-first, see log item 4); attempt 2 ALL CLEAN: 45 families × 23,022 examples full-suite + 2,044 selector top-up (K4 doubled budget) per seed, **0 divergences, 0 skips** (Phase-1 pending-skip ledger now EMPTY)
- [x] (5a) referee (a): NEW D15a runner feed built (`differential/test/bookmark-referee-feed.test.ts`, wired into `npm run referee:bookmark`): **98 fed / 94 ACCEPT / 4 expected-and-disclosed dataGroupId REJECTs** (real finding, filed R10.7-style — log item 5) / 5 error-vectors skipped by design
- [x] (5b) referee (b): handoff regenerated (byte-identical to committed — D9 drift-clean re-pin confirmed); selftests ok; structural **314/314 ACCEPT**; deep **123 ACCEPT / 2 REJECT / 189 SKIP_NON_INSIGHTS** — exactly the 2 standing frequency-filter true positives, nothing beyond
- [x] (6) `throwaway/b3-k1..k4` removed post-arbiter-signoff (`d7fa205` GO) + eslint throwaway glob/mjs-globals block + .gitignore + .prettierignore B3-era entries reverted (B0 `8f79b67` / B2 precedent)
- [x] (7) `npm run check` green at the final TS tree (102 files, 4,447 passed / 1,723 corpus-skips; browser smoke OK); conformance re-verified 1,528/0/1,723 at the final tree; `just check` green (Python); LOCAL commits both repos

## Gate working log

- (1) FLIP DONE: `batch-status.ts` — five vector-bearing prefixes + `bookmark_schema.` → done; header comment done/pending lists rewritten (the Discrepancy-#2 B2-binning caveat now moot — dropped). Collision assertion (mechanical, all corpus measured+setup api names, 424 distinct): exactly **14** names captured by the six flipped entries — the 14 vector-bearing B3 apis, all bound; **zero pending-batch names captured**. Dagger re-verify: all 299 B3 vectors carry `call.setup[]` length 0; zero foreign vectors carry a B3 setup api — gate delta = raw 299. Lock test updated (B2 precedent): new "B3 gate flip" case, 14/14 green.
- (2) CONFORMANCE CHECKPOINT — COUNTS MATCH: `npm run conformance` with the flip: **3,251 vectors — 1,528 PASS / 0 FAIL / 1,723 UNPORTED** @ corpus `70c904dc598d` (= 1,229 + 299; the +299 PASS delta was taken at bind time per B2 precedent — the flip is the straggler ratchet only, and no straggler fired). Report archived: `context/phase3/reports/2026-08-15-b3-gate.json`.
- (3) ORACLE PROBES — 17/17 (`/tmp/b3bind-oracle-probe.py` re-run, same script as B3-BIND): every B3 api answers call DATA on both bridges, `py_ok=True ts_ok=True equal=True`; bridge identities py 0.2.1 / ts 0.0.0, both `source_commit 70c904d…`.
- (4) DIFFERENTIAL REGRESSION — attempt 1 BLOCKED: full-suite replays at seeds 3343231 and 28631260 crashed with `UnencodableValueError: value nesting exceeds the codec depth guard` (falsifying api `bookmark_schema.validate_with_pydantic`). NOT a bridge divergence — a rig-strategy transport bug: `_B3_LEAF_VALUES` holds module-level MUTABLE containers; `_b3_schema_calls` inserted them BY REFERENCE (`st.sampled_from` hands out the constant itself) and later arms wrote through them, so nesting accumulated ACROSS examples until the codec depth guard fired (seed-dependent — bind seed 64091337 and arbiter seed 84150301 never drew the sequence; the P3-7 fresh/replay-seed mandate caught it, exactly the B0-attempt-1 pattern). REMEDIATION (fable rig fix, red-first TDD): `TestB3SchemaCallDomainIntegrity` in `conformance/tests/test_fuzz_harness.py` (identity-aliasing walk + encode-shippability + constants snapshot; red pre-fix on the aliasing assert), then `_b3_leaf()` deep-copy-at-draw helper in `strategies.py` (the discipline the choice-3 graft arm already had); all 5 mutation-arm `sampled_from(_B3_LEAF_VALUES)` sites rerouted. Attempt 2 ALL CLEAN — 4 seeds × (full suite 23,022 ex + selector top-up 2,044 ex at the K4 doubled ≥1,000 budget), 0 div, 0 skips, no repros; raw JSONs `conformance/differential/oracle/2026-08-15-b3-gate-seed*{,-selectors1000}.json`; RUN.md appended. Under-500 families are only the two documented finite-domain exhaustions (date_range 101, time_section 485). The `repros/` dir still holds exactly the two RESOLVED P2-9 triage records (commit 2d80135) — non-blocking, unchanged.
- (5a) REFEREE (a) — the D15a "runner feed" did not exist (D15a designed it; never built through B2 since referees first fire at B3). Built as `differential/test/bookmark-referee-feed.test.ts` (fable rig code) + wired into `npm run referee:bookmark`: executes the SAME registered binding the conformance runner replays for each of the 5 insights-shaped `bookmark_builders` apis (filter_entry 43, frequency_filter_entry 9, filter_section 9, group_section 27, time_section 10 output vectors = 98 fed; 5 group_section error-vectors skipped), canonicalizes the TS-built fragment to plain JSON, injects it into the recon known-valid `InsightsBookmarkParams` skeleton at the api's section slot, and requires ajv ACCEPT. `build_date_range` (common-shaped) and `build_flow_*` (flows-shaped) are EXCLUDED per the referee-(b) routing table — feeding them to the insights root is the documented D15a dead-weight trap. RESULT: 94 ACCEPT + **4 REJECTs, all `dataGroupId: must be string|null`** — a REAL finding (below), pinned exactly in the test (new rejects beyond the pinned set still block; a pinned vector turning ACCEPT also fails — unpin signal).
- (5) FINDING (real, filed, disclosed): the library threads `data_group_id: int | None` VERBATIM into clause-level `dataGroupId`; both independent analytics oracles type that slot `string | null` (vendored `DataGroupId` def in bookmark.json AND voluptuous `insights/validate.py:222,263,301,368` — the int form is legal only inside `raw_cohort` interiors, `:312,338`). First caught HERE because `sections.group` is the only schema-constrained feed slot (`GroupClause`, `additionalProperties: false`) and the referee-(b) handoff never feeds `build_group_section`. Filed `context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md` (R10.7: Python-first fix + re-extraction later; TS keeps replicating byte-for-byte; frequency-filter-precedent disposition). No live probe (Phase 3 runs nothing live) — recorded as a typed-contract mismatch, not a confirmed server rejection.
- (5b) REFEREE (b) — handoff regenerated from `conformance/vectors` (314 entries, byte-identical to committed — consistent with the D9-clean 70c904d re-pin); selftest controls passed for both oracles BEFORE the batches; structural 314/314 ACCEPT (jsonschema 4.26.0); deep 123/2/189 (voluptuous 0.16.0) — the 2 REJECTs are the standing frequency-filter true positives (exit 1 by design, `last-run-deep.json`); committed last-run reports changed only in `runtime_seconds` (determinism note holds).
- (6)+(7) CLEANUP + CHECKS — `throwaway/b3-k1..k4` deleted (arbiter GO `d7fa205` pre-dates deletion; probes re-run before deletion per B0 GF4 precedent); eslint/gitignore/prettierignore throwaway entries reverted; `npm run check` green (102 files / 4,447 passed / 1,723 corpus-skips / browser smoke OK); conformance re-verified at the final tree; `just check` green Python-side.

## Tier attribution (review findings + gate observations)

Module tier was opus (K1–K4); rig/review/gate tier fable. Attribution of every defect found after module hand-off:

| Finding | Introduced by (tier) | Caught by (tier/stage) | Class |
|---|---|---|---|
| F1 MAJOR — `bool <: int` dropped in cohort saved-vs-inline split (`buildCohortGroupEntry`/`buildCohortFilter`) | K2/K4 modules (opus) — a Python-semantics trap (`isinstance(int)` accepts bool) the packet's Caution #11 called out | fidelity reviewer (fable, P3-2d) via both-bridge probing; fixed by arbiter (fable, TS `7de21a8`) | correctness (in-annotation per ratified Discrepancy #8) |
| F2/F4 — dictKeyText float-carrier key spelling | K1 (opus) | reviewers (fable) | fidelity, minor |
| F3 — fromtimestamp OSError band understated | K3 (opus, disclosure wording) | fidelity reviewer (fable); promoted to Discrepancy #11 | disclosure accuracy |
| K1-D1 — integer-like `extra_forbidden` order | JS-engine limitation, not a tier defect | K1 module task disclosed it itself (opus) | standing divergence → Discrepancy #10 |
| Gate: `_B3_LEAF_VALUES` shared-mutable aliasing (harness transport crash at 2 replay seeds) | strategy authored at K1/BIND boundary; the aliasing idiom itself is FABLE-owned rig code (strategies.py) | gate task (fable) via the P3-7 replay-seed mandate | rig bug (not library) |
| Gate: `dataGroupId` int-vs-string contract mismatch | UPSTREAM Python library (predates the port) | NEW referee (a) feed (fable, this gate) | R10.7 latent-bug filing |

Observation for the tiering policy record: the opus modules shipped zero vector failures (299/299 first-run PASS at bind) and their harnesses were honest; the one MAJOR was a language-semantics trap explicitly listed in the packet cautions, caught by the fable review exactly as the "judge stronger than judged" design intends. Both gate-time discoveries were fable-owned surfaces (rig strategy, referee feed) — no downward-tier leakage.

## Discovered facts / measurements

- The B2-era 2,539-example skip ledger is fully discharged: this gate ran the program's first ALL-LIVE full-suite differential (45 families, zero `skipped_per_target` entries > 0).
- Full-suite runtime is ~20s/seed (23k examples) — the 4-seed × 2-run matrix costs ~3 minutes; replaying every prior gate seed remains cheap and should stay standing posture through B6.
- `sections.filter` and `sections.time` items are `JsonValue` in the vendored schema — referee (a)'s discriminating power for B3 lives almost entirely in the `sections.group` slot (`GroupClause`, `additionalProperties: false`). Recorded so B6/W3 doesn't over-read filter-slot ACCEPTs (same caveat family as the structural near-vacuousness note in the referee-(b) README).
- `st.sampled_from` over a tuple containing mutable containers hands out the CONSTANTS by reference — any strategy whose downstream mutates drawn values in place must copy at draw time. Candidate R10.4 watch item (1st recurrence; the choice-3 graft arm had already hit and solved it locally with a json round-trip, so treat as 2nd sighting of the idiom).

## Post-gate handoff

- B4 may start (P3-1 hard barrier released). Corpus pin 70c904d; entering report for B4: 1,528/0/1,723; B4 gate delta 842 (P3-1 † footnote).
- Open R10.7 items carried forward: frequency-filter clause shape (2 deep-referee REJECTs) + NEW dataGroupId int threading (4 ajv-feed REJECTs, pinned) — both need a Python-first fix + re-extraction cycle, neither blocks Phase-3 batches.
- Referee (a) feed is data-driven: at B5/B6 add `workspace.build_params` (insights, as-is) to `FEED_SLOTS` per the D15a feed rule.
