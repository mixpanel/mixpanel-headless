# B5 batch notes

**Status**: CLOSED — gate passed 2026-08-16 (this commit). Conformance
**2,876 PASS / 0 FAIL / 375 UNPORTED** @ corpus pin `70c904dc598d`
(gate delta +506 exactly; report
`context/phase3/reports/2026-08-16-b5-gate.json`). File originally
created by the B5 arbiter (B5-ARB) to carry the outbound-deferrals
ledger (assertions review F2, `b5-review-resolution.md`); finalized by
the B5 GATE task per P3-2 step (e) item 5 — the "§ Gate record" and
"§ Tier observations" sections below are the gate's additions, the
ledger and arbiter summary are PRESERVED verbatim (arbiter instruction
3, `b5-review-resolution.md`).

Shard notes: `B5-S1-notes.md` · `B5-S2-notes.md` · `B5-S3-notes.md` ·
`B5-BIND-notes.md`. Reviews: `../design/b5-review-fidelity.md` ·
`../design/b5-review-assertions.md`. Arbiter resolution:
`../design/b5-review-resolution.md`.

## Outbound deferrals to B6 (BINDING ledger — the B6 design-lite packet MUST cite this section)

| # | Item | Owner | Source of record | What B6 must do |
|---|---|---|---|---|
| 1 | `TestDiscoveryCacheAcrossUse` (`tests/unit/test_query_workspace_scoping.py:401`) | **B6-W1** | `b5-packets.md` §8 (packet-cited) + `facade-scoping.test.ts` header | Translate into `packages/core/test/workspace/facade-scoping.test.ts` once `Workspace.use()` lands (`use()` discards `self._discovery` — the cache-drop invariant). |
| 2 | `TestWorkspaceFacadeScoping` (`tests/unit/test_query_workspace_scoping.py:379`) | **B6-W1** | `facade-scoping.test.ts:1-25` header ONLY (packet §3 routed it to B5 on the wrong assumption that the facade half was `use()`-free; the case calls `ws.use(workspace=4242)`, a B6-W1 stub) | Translate into `facade-scoping.test.ts` — the additive session-pinned lock already there makes this a one-line delta. This is the only Python lock on `use()`-workspace-scoping threading through the facade. |
| 3 | `TestListCustomPropertiesErrorHandling` (`tests/unit/.../list_custom_properties` suite, facade re-raise contract `workspace.py:7742-7790`) | **B6** (api-map: `workspace.list_custom_properties` batch B6) | `custom-property-query.test.ts:9-22` header ONLY (packet said "translate against the B4 client method", but the B4 client does no `displayFormula` QueryError re-raise — the contract lives in the facade member) | Translate with the facade member: assert `raised is not original`, `__cause__`/`cause` is the original, HTTP context carried over. |
| 4 | `workspace.list_bookmarks_v2` pending-override REMOVAL | **B6 gate** | playbook P3-5 flip rules (B5-gate adds the longer `pending` entry; B6-gate replaces the 44 exact names + override with `workspace.` → done) | Mechanical, part of the B6 flip commit. |
| 5 | R11.7 straggler: `types/results/query-engine.ts` `overall_conversion_rate` NON-STRING ladder (`floatValue(value) ?? 0.0` where CPython `float(None/list/dict)` raises `TypeError`) | **B6 gate** (R11.7 straggler sweep) | `b5-review-resolution.md` ASR-F6b (the STRING arm was fixed at B5-ARB via `pythonFloat`; the non-string ladder needs a `pythonFloatCoerce` compat twin — a B0-style both-repo addition, out of arbiter-patch scope) | Add `pythonFloatCoerce` to `packages/core/src/compat/` mirrored in `pycompat_ref.py` (+ oracle strategy), then route the non-string arm through it. Blame: P2-6 commit `2ee9f59`, pre-R11.7-amendment. |

## Arbiter remediation summary (2026-08-16)

See `context/phase3/design/b5-review-resolution.md` for the full
findings ledger, fixes (all red-first), and post-fix re-run evidence
(S1/S2/S3 harness seeds, BIND fuzz with the extended rrweb timestamp
domain, 506-vector replay, `npm run check`, `just check`).

## Gate record (B5-GATE, fable, 2026-08-16)

TS gate commits (main): `c66b2d9` (flip + checkpoint), `bfe1b37`
(referee (a) feed extension), `44734be` (throwaway cleanup). Python
gate commit: this one.

- [x] (1) **Flip, one commit with the checkpoint** (`c66b2d9`): the 44
  exact-name `workspace.<member>` entries → `done` (jq-generated from
  the api-map `batch=="B5"` rows, verified identical to the packet §7
  list), `replays.` + `replay_labels.` + `rrweb_analyzer.` → `done`,
  **plus the `workspace.list_bookmarks_v2` → `pending` override**
  (removed at B6 — ledger item 4). Standing collision assertion re-run
  over all 424 corpus api names (measured + setup): 6 startsWith hits,
  5 same-batch (harmless, flip together), the ONLY cross-batch hit is
  `workspace.list_bookmarks` → `workspace.list_bookmarks_v2`, resolved
  by the override — exactly the packet §7.1 measurement. Batch-status
  unit suite extended with the B5 flip lock (44-name table + override +
  prefix assertions); UNPORTED anchors re-pointed to B6 names
  (`workspace.me` / `workspace.list_dashboards`).
- [x] (2) **Conformance checkpoint**: 3,251 vectors — **2,876 PASS /
  0 FAIL / 375 UNPORTED** @ `70c904dc598d`, byte-equal to the packet §7.2
  expectation and to the pre-flip BIND counts (every bound name already
  replayed; the flip is purely the straggler ratchet). Attribution:
  +506 = 480 `workspace.<B5-member>` + 26 replays-family
  (`replays.` 8 + `replay_labels.` 16 + `rrweb_analyzer.` 2); 375
  UNPORTED = 353 B6 `workspace.*` + 14 `region_probe.` + 7 `oauth_flow.`
  + the 1 P3-1 † carried holdback
  (`auth/api_client.resolve_workspace_id/...` on its `workspace.me`
  setup — first PASS at B6, gate delta 354 there). **workspace.me
  decision (packet §6.8): B6-owned, NOT bound at B5 — no +1 here.**
- [x] (3) **Oracle probes**: 9/9 newly registered builder-kind apis
  (five `workspace.build_*params`, three `replay_labels.*`,
  `rrweb_analyzer.analyze`) answer call DATA on BOTH bridges
  (oracle-py 0.2.1 / oracle-ts 0.0.0, both source_commit `70c904dc…`,
  protocol 1.1), canonical outcomes pairwise equal. Wire names exempt.
- [x] (4) **Differential full-suite regression — CLEAN after one
  rig-strategy remediation** (the B3-gate precedent): fresh seed
  **47824574** + replays of EVERY prior gate seed (**3343231** B2,
  **28631260** B0, **52794688** B0, **40075993** B3, **53062695** B4)
  over the cumulative **54-family** surface. First pass: 4/6 clean;
  seeds 3343231 + 52794688 each drew ONE `rrweb_analyze_family`
  divergence — the console-payload `[18.0, None]` member joined into
  the console message (py `"18.0 None"` / ts `"18 None"`): the
  **Discrepancy #12 sanctioned class** (the discrepancy names the
  "rrweb console-message join" surface explicitly) escaping through a
  strategy-domain gap the B5-BIND F1 exclusions missed (console-payload
  slot). Remediated in `strategies.py` (`[18.0, None]` → `[18.5, None]`
  + #12 domain note); shrunken repro verified #12-class and deleted;
  ALL SIX seeds re-run against the final domain: **27,577 examples /
  0 skips / 0 divergences** per seed, exit 0. Raw JSONs
  `conformance/differential/oracle/2026-08-16-b5-gate-seed*.json`;
  RUN.md appended; `repros/` back to the two RESOLVED P2-9 records.
- [x] (5) **Referees — RUN at this gate** (the P3-7 conditional clause
  fires: S2's `build_params` EMITS insights bookmark params, packet
  §7.4; note this OVERRIDES the bare "referees not required at B5"
  reading of P3-7 — the clause is part of P3-7 itself): (a) ajv feed
  extended with the 115 `workspace.build_params` full payloads AS-IS
  (213 fed): 208 ACCEPT + **5 pinned expected-and-disclosed dataGroupId
  REJECTs** — the 4 standing B3 clause-level pins + ONE NEW SITE
  (sections-level `dataGroupId` int, `workspace.py:2278`, rejected as
  `/sections: must NOT have additional properties`; same R10.7
  `data_group_id` threading family, addendum appended to
  `context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md`;
  the deep voluptuous oracle tolerates the key, which is why referee (b)
  never saw it). (b) round-trip over the regenerated handoff
  (byte-identical, 314 entries): structural **314/314 ACCEPT**, deep
  **123 / 2 REJECT / 189 SKIP** — the 2 standing frequency-filter true
  positives only (expected, exit 1 by design). **No NEW reject on
  either referee — non-blocking.** Selftest controls passed before both
  batches.
- [x] (6) **Deferral audit**: every inbound §8 item verified ON DISK —
  bypass halves (`validation-bypass{,-r2}.test.ts`), facade validation
  classes (`query-validation-facade.test.ts`), transform tests
  (`transform-{funnel,retention}.test.ts`), query-user edge/structural
  files, `TestMeasurementPropertyBuilder` append,
  `build-params-equivalence.pbt.test.ts`, the three replay label fns
  exported from `replays/replay-labels.ts` + `index.ts`, the
  `toExpectError` errors[] extension (BIND). `throwaway/b5-{s1,s2,s3,bind}`
  removed (`44734be`) — RUN records live in the four shard notes files.
- [x] Checks: `npm run check` green (175 files, 8,154 passed / 375
  skipped, browser smoke OK); `just check` green (Python — strategies.py
  + referee reports + notes touched).

## Tier observations (P3-2e item 5; opus findings attribution)

B5 ran the revised two-tier program (fable + Opus 5, tiering revision
2026-08-15): S1/S2/S3 module+Layer-3 work on opus, packet/BIND/reviews/
arbiter/gate on fable. Observations for the B6 packet author:

1. **All 5 fidelity findings and 5 of 6 assertion findings landed on
   opus-authored shard code** (FID-F1..F5, ASR-F1/F3/F4/F5 + ASR-F2's
   ledger gap; ASR-F6b was Phase-2 blame, pre-R11.7). The two MAJORS
   worth pattern-watching at B6 volume: (a) exception-CLASS drop on
   `pytest.raises(<Class>, match=…)` translations — ~55 sites across 6
   S2 files, remediated to 86 class asserts (R10.2 diff at review
   caught it; B6 has 16 CRUD test files of the same shape); (b) the
   in-annotation raise-emulation sweep (FID-F2) — opus systematically
   preferred defensive narrowing over CPython raise twins at transform
   read sites.
2. **Watchlist #13 recurrence count now 5** (`isPlainDict`
   re-derivation, ASR-F3). One more recurrence triggers the R10.4
   stop-amend-regenerate threshold conversation.
3. **Discrepancy #12 filed at this batch** (integral-float spelling in
   OUTPUT text): the class since surfaced once more at the GATE itself
   (console-payload strategy slot, item 4 above) — B6 shards emitting
   any float-typed value into rendered text must carry the domain note
   up front.
4. **Opus first-attempt quality on the volume center was high**: 505 of
   506 vectors passed on the first full BIND replay (one S3
   cause-in-details leak); zero escalations to the P3-3 retry rule;
   both harness RUN records reproduced exactly at review.
5. **Rig work stayed fable end-to-end** (bindings, batch-status,
   referee feed, strategy remediation) — the two gate-time issues
   (console-slot domain gap, referee pin semantics for a non-dataGroupId
   error string) were both rig-side, consistent with the "judge must be
   stronger than the judged" allocation.

## Discrepancies & escalations

- Discrepancies filed at B5: **#12** (playbook, arbiter-promoted
  ASR-F6a). No new discrepancy at the gate — the rrweb console
  divergence and the referee's new REJECT site are instances of #12 and
  the standing dataGroupId R10.7 report respectively, both handled
  inside existing rulings.
- Escalations: **none** (no module task missed done-criteria; no R10.4
  threshold crossed — watchlist #13 stands at 5, noted above).
- Referee posture for B6 (standing): referees (a)+(b) re-run at the B6
  gate per P3-7; the ajv feed now carries 6 apis and 5 pins; the pinned
  set must be re-checked against any Python-side dataGroupId fix cycle.
