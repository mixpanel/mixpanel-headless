# B9 batch notes — the browser package (gate record) · **PHASE 3 CLOSES**

**Status**: B9 GATE CLOSED · 2026-08-16 · fable, ≤ high (task B9-GATE,
P3-2e instantiated as the Phase-3 TERMINAL gate). Packet:
`context/phase3/design/b9-packets.md` §5 (+ §9 spike addendum with the
ARB-A erratum, + §10 ARB-B errata — the gate consumed the AMENDED forms).
Shard notes: `B9-R1-notes.md`, `B9-R2-notes.md`, `B9-spike.md`
(dispatch-named spike evidence of record; `B9-D2-SPIKE-notes.md` is a
pointer). Reviews (DOUBLED per P3-3 — two independent pairs, pair B
BLIND, + per-pair arbiter):
`b9-reviewA-{semantics,assertions}.md` + `b9-reviewA-resolution.md`
(fixes TS `4b1884a`); `b9-reviewB-{threat,e2e}.md` +
`b9-reviewB-resolution.md` (fixes TS `de08f1f`). Both resolutions:
**GO** (pair B's initial NO-GO resolved by FB-1..FB-11, all applied
red-first and verified).

## MILESTONE

> **This gate closes Phase 3. The corpus HELD: 3,251 PASS / 0 FAIL /
> 0 UNPORTED @ corpus pin `70c904dc` — unchanged from the B8 close
> (B9 owns zero vectors; the gate check is the INVERTED one: any delta
> would have been a regression).** The batch delivered
> `@mixpanel-headless/browser` per plan §4.1/§4.3 + R9.3 (CredentialStore,
> redirect PKCE over core WebCrypto, `oauth_token` first-class, SA
> runtime refusal on 7 enumerated paths, export-transport exclusion),
> promoted the browser package to a REAL bundle-smoke target, and
> classified the D2 spike **ACCEPTED** (PKCE-in-browser ships ENABLED).

## Gate checkpoint (P3-2e items 1–2, inverted per packet §5.1)

- **No flip**: `batch-status.ts` UNTOUCHED — terminal since the B8 flip
  `b59567c`; B9 owns no prefix. Verified mechanically: `git log
  b59567c..HEAD -- conformance-runner/` is EMPTY (zero rig commits in the
  entire batch — caution #8 held), and the gate commit `8fa150d` touches
  only `throwaway/` deletions. The terminal batch-status tests (zero
  pending entries; every corpus api name resolves `done`) ran green
  inside `npm run check`.
- **Conformance report**: `npm run conformance` → **3,251 vectors —
  3,251 PASS / 0 FAIL / 0 UNPORTED** @ corpus `70c904dc598d`, verified
  TWICE at this gate (pre-cleanup at `de08f1f` and re-verified at the
  final HEAD `8fa150d`). HOLD confirmed — delta over B8: **zero**, as
  demanded. Archived: `context/phase3/reports/2026-08-16-b9-gate.json`.
- **Checks**: `npm run check` green at the final TS HEAD `8fa150d`
  (typecheck ×5 incl. `packages/browser`, eslint with the purity
  boundary EXTENDED to `packages/browser` (§0.4), prettier,
  **9,958 tests / 243 files**, and the PROMOTED two-entry browser-bundle
  smoke: `packages/core/src/index.ts` + `packages/browser/src/index.ts`
  bundled for `--platform=browser`, 2,069,265 bytes). Python repo:
  docs/report/ledger commits only (this file, the playbook flip, the
  Phase-4 ledger, RUN.md, report + seed JSONs); `just check` green — see
  Gate commits below.

## Oracle probe + differential regression (P3-2e item 3 / P3-7 / packet §5.2)

- **Oracle probe: VACUOUS this batch, stated explicitly** (packet §5.2.2)
  — B9 registered ZERO new oracle families and ZERO api names
  (`strategies.py` untouched by any B9 commit, verified via `git log`;
  api-map B9 extraction = 0 members). Cumulative surface stays
  **55 families**. Compensating controls for the no-second-oracle auth
  surface (Risk 7): full Layer-3 per §2.6/§3.4, the DOUBLED BLIND review,
  and the two direct-CPython differentials below.
- **Differential full-suite regression** (fresh seed + replay of EVERY
  prior gate seed, ≥500/family, oracle-py ↔ oracle-ts): RUN record
  appended to `conformance/differential/oracle/RUN.md` (B9 terminal
  section) — fresh **1059451707** + replays **3343231** (B2),
  **28631260** (B0), **52794688** (B0), **40075993** (B3), **53062695**
  (B4), **47824574** (B5), **628997442** (B6), **715310894** (B7),
  **419393897** (B8) — **10 seeds total; 28,091 examples / 0 skips /
  0 divergences per seed, all ten; exit 0, status `ok`, no repros
  written.** Under-500 families: only the two documented finite-domain
  exhaustions (`build_date_range_family` 101, `build_time_section_family`
  485). Bridges: oracle-py 0.2.1 @ support branch, oracle-ts 0.0.0 @
  `main` (`de08f1f` tree), both `source_commit 70c904dc598d…`, protocol
  1.1. `repros/` unchanged (the two RESOLVED P2-9 records). Raw JSONs:
  `2026-08-16-b9-gate-seed{…}.json` ×10.
- **Direct-CPython differentials re-verified from their recorded seeds**
  (packet §5.2.3, spot-check tier, BEFORE throwaway removal):
  `throwaway/b9-r1/pkce-differential.ts` → 601 verifiers @ seed 20260816,
  **0 divergences** (reproduces the R1 RUN record);
  `throwaway/b9-r2/redirect-parse-fuzz.ts` → 709 cases @ seed 20260817,
  **0 divergences** (reproduces the R2 RUN record).

## Referees (P3-7 — full-corpus CLOSE-OUT SWEEP, one more time per the gate directive)

B9 touches no bookmark source, but the gate ran BOTH referees as the
Phase-3 closing sweep:

- **(a) ajv draft-04 runner feed** (`npm run referee:bookmark`): 9/9
  tests green — feed + pin-exactness asserted in-test; the only REJECTs
  are the pinned EXPECTED-AND-DISCLOSED `dataGroupId` int-threading set
  (R10.7, Phase-4 fix-queue item 2(b)).
- **(b) bookmark_parser round-trip** (analytics checkout, READ-ONLY):
  handoff regenerated **BYTE-IDENTICAL** (314 entries — no drift since
  B6); selftest controls passed for BOTH oracles first; structural
  **314/314 ACCEPT**; deep **123 ACCEPT / 2 REJECT /
  189 SKIP_NON_INSIGHTS** — the 2 standing frequency-filter true
  positives only (exit 1 by design; Phase-4 fix-queue item 2(a)). Fresh
  reports identical to the committed `last-run-{structural,deep}.json`
  modulo `runtime_seconds` (not re-committed).
- **No NEW reject on either referee — nothing to triage.** Referee (c)
  stays CI-passive.

## R10.9 RUN records (mirrored from the shard notes; `throwaway/b9-r1`,
`throwaway/b9-r2`, and the pair-B driver dir `throwaway/b9-reviewB-e2e`
removed by this gate after BOTH arbiter sign-offs — P3-2c + the
resolutions' cleanup notes)

### B9-R1 (`throwaway/b9-r1/`, deleted)

```
edges:             32 checks / 0 failures (post-ARB-A expectation update:
                   token_env-in-browser = OAUTH_TOKEN_ERROR; reproduced
                   post-ARB-B unchanged)
store-fuzz:        500 runs, fast-check seed 20260816, 0 divergences
                   (in-memory model vs localStorage-adapter SUT)
pkce-differential: 601 verifiers (seed 20260816; RFC 7636 Appendix-B
                   anchor + 600 random, lengths 43–128 + 86-char
                   production shape) vs live CPython — 0 divergences
```

### B9-R2 (`throwaway/b9-r2/`, deleted)

```
edges:               35 checks / 0 failures (every §3.5.1 error branch;
                     post-FB-5 clock addendum disclosed in the R2 notes)
pkce-vectors:        601 @ seed 20260817 THROUGH the browser entry point
                     — 0 divergences
redirect-parse-fuzz: 709 (700 fast-check + 9 TestParsePastedRedirect
                     anchors) @ seed 20260817 vs live CPython
                     _parse_pasted_redirect — 0 divergences
```

All harness legs were re-run/reproduced from the recorded seeds by the
review pairs (P3-2d item 5) and the two differential legs again by this
gate (§5.2.3 above).

## DOUBLED BLIND review convergence summary (P3-3 auth doubling — B9)

Protocol: two independent pairs (4 reviewers) + per-pair arbiter; pair B
BLIND (Python sources + TS diff + R9.3/plan-§4.3 contract text only).
Verdicts: pair A **GO** (lens 1: 1 minor code-choice finding SEM-F1;
lens 2: GO, 1 docs finding + 3 observations); pair B **NO-GO → GO**
(lens 1 threat: 2 blocking; lens 2 e2e: 46 checks, F1–F3 + 3 minors;
arbiter: 11 deduped findings ALL CONFIRMED — 2 blockers + 6 majors +
3 minors, all applied red-first at `de08f1f`).

**The doubling earned its cost most clearly of the three auth batches**
(pair-B arbiter's convergence note, adopted here as the program record):
pair A, anchored by the packet's §2.3 path enumeration, went GO with zero
blockers; the BLIND pair re-derived the SA-ingress surface from R9.3
alone and found **two reproduced auth-policy bypasses the enumeration
missed** — FB-1 (`withProject` derived-client guard escape) and FB-2
(raw `Workspace` VALUE re-export bypassing both browser gates) — now
packet §10 path-table rows 6–7. Within pair B the two lenses converged
independently on FB-1/FB-5/FB-8 with different drivers and partitioned
cleanly elsewhere; zero contradictions between pairs; the corpus HOLD and
all RUN records reproduced at every review stage. Full record:
`b9-reviewA-resolution.md` + `b9-reviewB-resolution.md` (read together).

## D2 spike (plan §8 open-question 3 — CLOSED)

**ACCEPTED** (`B9-spike.md`; packet §9 + ARB-A erratum): DCR attempt 1 →
HTTP 201 with `client_id` for a third-party https redirect URI. Budget:
creds check 1/1 PASSED, DCR 1/2, Query-API 0/2 (contingency unused), + the
sanctioned optional authorize-URL GET (302 — well-formedness only).
Tier-C posture: **PKCE-in-browser ships ENABLED**; `oauth_token` stays
first-class and README-leading. Docs carry the corrected tense
("consent/exchange **to be verified** in Phase-4 live burn-in") — no e2e
claim anywhere. Residue + the §4.5 unverified triple → Phase-4 ledger
rows 4/7 (`context/phase4/inbound-ledger.md`).

---

# Phase 3 — CLOSED (summary block, packet §5.3)

**Phase 3 is COMPLETE.** The full conformance corpus is green in
TypeScript and held through the terminal batch:
**3,251 PASS / 0 FAIL / 0 UNPORTED @ corpus pin `70c904dc`**
(3,179 recorded + N=72 authored `compat.*`, per the P3-1 `:107`
end-state). Playbook status header flipped in the same docs commit as
this file.

## Batch ledger B0 → B9 (gate dates, TS gate commits, PASS trajectory)

| Batch | Gate date | TS gate/flip commit | Conformance at gate (PASS/FAIL/UNPORTED) | Report |
|---|---|---|---|---|
| B0 (compat + client internals) | 2026-08-15 | `8f79b67` (gate; remediation `3c07d4e`) | 539 / 0 / 2,712 @ `b5c1369` | `reports/2026-08-15-b0-gate.json` |
| B2 (validators) | 2026-08-15 | `794fea1` (attempt 2; remediation `ad830fb`) | 1,229 / 0 / 2,022 | `reports/2026-08-15-b2-gate.json` |
| B3 (builders) | 2026-08-15 | `cb192f2` | 1,528 / 0 / 1,723 @ `70c904d` (B3-BIND re-pin) | `reports/2026-08-15-b3-gate.json` |
| B4 (api_client + pagination) | 2026-08-16 | `d57b7a4` | 2,370 / 0 / 881 | `reports/2026-08-16-b4-gate.json` |
| B5 (services + rrweb + facade query half) | 2026-08-16 | `c66b2d9` | 2,876 / 0 / 375 | `reports/2026-08-16-b5-gate.json` |
| B6 (workspace facade, 158 members) | 2026-08-16 | `1aab800` | 3,230 / 0 / 21 | `reports/2026-08-16-b6-gate.json` |
| B7 (accounts/session/targets + resolver) | 2026-08-16 | `9fb09ef` | 3,244 / 0 / 7 | `reports/2026-08-16-b7-gate.json` |
| B8 (node package) | 2026-08-16 | `b59567c` (+ cleanup `4095f46`) | **3,251 / 0 / 0 — corpus closes** | `reports/2026-08-16-b8-gate.json` |
| B9 (browser package — terminal) | 2026-08-16 | `8fa150d` | **3,251 / 0 / 0 — HOLD** | `reports/2026-08-16-b9-gate.json` |

PASS trajectory: 539 → 1,229 → 1,528 → 2,370 → 2,876 → 3,230 → 3,244 →
3,251 → 3,251 (HOLD). FAIL was **zero at every gate**. Corpus pins:
`8ae76314` (Phase-2 exit) → `b5c1369` (B0-1 authored vectors) →
`70c904d` (B3-BIND adapter retarget) — final; both re-pins D8/D9
drift-checked clean (all recorded vectors byte-identical).

Gate-notes index: `B0-notes.md` … `B8-notes.md` + this file. Packets:
`design/b{0(=P3-4),2,3,4,5,6,7,8,9}-packets.md`. Review records:
`design/b*-review*.md` (single pairs B0–B6; doubled pairs B7–B9, pair B
blind at B8–B9 with per-pair arbiters).

## Discrepancy / deviation registry (playbook §P3-8 log — final status)

**#1–#15 recorded; #13 CLOSED-FIXED; all others standing-disclosed with
re-examine triggers** (live-observability triggers collected as Phase-4
ledger row 6): #1 R2.5 jitter wording (proposed amendment); #2
batch-status comment binning (corrected at B3); #3 tiering "205 members"
sizing note; #4 B0 LOC estimate note; #5 `me.py` split (B4-C1/B8-N2 —
executed as designed); #6 >2^53 Retry-After reads absent; #7 `safeInt`
>2^53 default; #8 out-of-annotation scalars class; #9 S4
integer-like-key warning order; #10 `extra_forbidden` integer-like-key
order; #11 gmtime-overflow OSError class; #12 integral-float spelling
narrowing class; **#13 first-org pick ordering — CLOSED-FIXED at B8
(user ratification 2026-08-16 → B8-MAPFIX `597ef7d`)**; #14 `\d` ASCII
narrowing at the bridge `project` twins; #15 config default path
import-time vs call-time. The optional #9/#10 residual-site HUMAN-CALL
(order-insensitive comparison) remains open, optional, non-blocking.

## Rulebook amendments filed during Phase 3 (R10.4)

- **R11.7** (B0 gate): `pythonStrip`/`pythonInt` mandatory for every
  blank-check / `int(str)` twin — bare `trim()`/`parseInt` forbidden
  (13 recurrences at the B0 gate, remediation `3c07d4e`).
- **R11.8** (B8 pair-A arbiter): except-clause class mapping,
  clause-for-clause (8 recurrences).
- **R11.9** (B8 pair-B arbiter): pydantic-lax datetime twins + the
  writer-formatter byte-parity table (8 recurrences; explicitly bound
  B9's browser CredentialStore — honored, locked by
  `packages/browser/test/token-serialization.test.ts`).

## Escalations (program-wide, final)

**Zero P3-3 two-failure aborts across all nine batches.** B5/B6/B7/B8/B9
gate notes each record "escalations: none"; B0–B4 recorded none either.
Two GATES ran a second attempt after R10.9/differential findings at the
gate itself (B0: the R11.7 trim/parseInt divergence class, remediation
`3c07d4e` → gate attempt 2 PASS; B2: the GroupBy decode-time float-ness
divergence, remediation `ad830fb` → gate attempt 2 PASS) — gate-loop
remediations per the P3-2e protocol, not module-task escalations.
Non-escalation incidents for the record: the B2-M1 attempt-1 harness
alias mis-resolution (Sonnet 4.5) was harness-killed and triggered the
2026-08-15 TIERING REVISION (Sonnet removed; two tiers only — fable +
Opus 5 pinned via `ANTHROPIC_DEFAULT_OPUS_MODEL`); B3's K1-D1 went to
its arbiter inside the review protocol and became Discrepancy #10; both
R10.4 threshold crossings at B8 became amendments (R11.8/R11.9), not
stops. B9's pair-B NO-GO was resolved inside the doubled-review protocol
(FB-1..FB-11 applied; GO).

## Doubled-review convergence stats (B7/B8/B9 — the auth-doubling record)

| Batch | Pair A | Pair B (blind at B8/B9) | Convergence highlight |
|---|---|---|---|
| B7 | GO — 3 minor + 3 nits | GO — 1 minor + 2 doc fixes + 2 disclosures | Both pairs hit the org-order integer-key class independently (→ Discrepancy #13, later user-ratified to a FIX at B8) |
| B8 | GO — 2 MAJOR + 6 minor | GO — lens-1 0 findings; lens-2 1 MAJOR + 3 minor | **DISJOINT MAJORS** — wiring defect (A) vs value-domain defect (B); single-pair review would have shipped one of the two |
| B9 | GO — 1 minor code + 1 docs + 3 obs | **NO-GO → GO** — 2 BLOCKERS + 6 major + 3 minor | Blind pair found 2 SA-refusal bypasses (paths 6–7) the packet enumeration + sighted pair missed — the strongest single data point for BLIND doubling on auth batches |

Verdict: the doubling paid for itself at every auth batch, escalating in
value as the surface got less Python-twinned; keep it for any Phase-4+
work on auth surfaces.

## Tier attribution stats (two-tier program: fable + Opus 5)

Per-batch "tier observations" sections are the sources of record
(`B2-notes.md` "Volume-tier observations", `B5-notes.md` /
`B6-notes.md` "Tier observations"); aggregate:

- Volume tier (opus): B2/B3/B5/B6 module + Layer-3 work. First-attempt
  quality high on facade/delegation code (B6: 353/353 vectors green at
  first BIND replay; B5: zero P3-3 escalations) — but review findings
  concentrated on opus-authored shard code (B5: all 5 fidelity + 5 of 6
  assertion findings), confirming the fable-review posture.
- Fable tier: all rig code, all bindings, all reviews/arbiters/gates,
  B0/B4/B7/B8/B9 modules. All five fable batches first-attempt green.
- Tiering revision 2026-08-15 (Sonnet removed) held for the rest of the
  program with zero further alias incidents.

## B9 spike classification

**ACCEPTED** — see the D2 section above; evidence `B9-spike.md`; docs
posture landed at TS `f6f298b` (+ tense erratum in `4b1884a`).

## Outbound ledger (Phase-4 handoff — BY REFERENCE)

The single collection point Phase-4 planning reads is
**`context/phase4/inbound-ledger.md`** (written by this gate; renders
packet §5.5 as amended by §10.5, plus the mechanical sweep of every
batch-notes outbound section). Row summary: (1) O1 OAuth error-details
token-payload exposure — ESCALATED to the R10.7 queue; (2) the R10.7
Python-fix queue, now FOUR items (a–d) with re-pin choreography; (3) the
JsonNumber >2^53 facade round-trip gap; (4) live-parity Layer-4 setup
incl. the 60 q/hr rate-limit sharding and the live-auth scenarios (with
the browser-PKCE e2e triple); (5) R9.2 TOCTOU residue; (6) standing
discrepancy re-examine triggers + the optional #9/#10 HUMAN-CALL;
(7) D2 spike residue (client cleanup, eu/in posture); (8) browser
refresh surface on the D2-ACCEPTED branch; (9) packaging/awareness items
(`exports` asymmetry, TTL/loopback defaults, cross-tab non-goal,
SA-guard core-seam recommendation).

## Gate commits

- TS `main`: `8fa150d` (terminal gate: throwaway/b9-r1 + b9-r2 +
  b9-reviewB-e2e removal after both arbiter sign-offs; no flip — nothing
  to flip; `npm run check` + `npm run conformance` green at HEAD).
- Python support branch: this file + `2026-08-16-b9-gate.json` +
  `differential/oracle/RUN.md` B9 terminal section + the 10 seed JSONs +
  `context/phase4/inbound-ledger.md` + the playbook PHASE-3-COMPLETE
  status flip (all in the closing docs commit(s); shard/spike/review
  files were committed by their own tasks).

**Phase 3 is closed. Next: Phase 4 (burn-in) per
`context/phase4/inbound-ledger.md` and plan §6.**
