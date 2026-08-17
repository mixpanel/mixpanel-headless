# B8 batch notes — the node package (gate record) · **THE CORPUS CLOSES**

**Status**: B8 GATE CLOSED · 2026-08-16 · fable, ≤ high (task B8-GATE,
P3-2e). Packet: `context/phase3/design/b8-packets.md` §5 (flip spec incl.
the terminal UNPORTED-probe re-anchor). Shard notes: `B8-MAPFIX-notes.md`
(user-ratified org-ordering fix), `B8-N1-notes.md`, `B8-N2-notes.md`,
`B8-N3-notes.md` (RUN records mirrored below). Reviews (DOUBLED per P3-3 —
two independent pairs, pair B BLIND, + per-pair arbiter):
`b8-reviewA-{semantics,assertions}.md` + `b8-reviewA-resolution.md`
(fixes `92a5f8a`); `b8-reviewB-{atrest,e2e}.md` +
`b8-reviewB-resolution.md` (fixes `e44bea2`). Both resolutions: **GO**.

## MILESTONE

> **At this gate the FULL conformance corpus is green in TypeScript:
> 3,251 PASS / 0 FAIL / 0 UNPORTED @ corpus pin `70c904dc`.** This
> satisfies the playbook P3-1 `:107` end-state (3,179+N, N=72) one batch
> early — B9 is spike-scoped (tests only, zero vectors); the B9 gate
> must merely HOLD 3,251/0/0 while adding tests (b8-packets.md §8
> outbound row 5, for the B9 packet author).

## Gate checkpoint (P3-2e items 1–2)

- **Flip**: `batch-status.ts` `oauth_flow.` → `done` (TS gate commit
  `b59567c` on `main`; flip + report checkpoint + terminal re-anchor in
  the same commit per P3-2e item 1 / packet §5.3). The table now
  contains **ZERO pending entries** — terminal state recorded in the
  file's header comment.
- **Standing collision assertion** (recorded scan, corpus pin
  `70c904dc`, measured + `call.setup[]` apis): the only corpus api name
  matching the flipped prefix is `oauth_flow.refresh_tokens` (×7);
  **NOTHING remains pending** — zero still-pending corpus api names
  (there are no pending entries left to shadow), re-asserted mechanically
  by the new terminal test ("every corpus api name resolves done") in
  `batch-status.test.ts`. Zero collisions — as predicted by packet §5.1.
- **Conformance report**: `npm run conformance` →
  **3,251 vectors — 3,251 PASS / 0 FAIL / 0 UNPORTED** @ corpus
  `70c904dc598d`. Attribution: PASS +7 over the B7 baseline (3,244)
  = exactly the B8 gate delta (the 7 `oauth_flow.refresh_tokens`
  vectors, bound at B8-N2 and passing-while-pending since the shard
  commit `53a134e`; no P3-1 † adjustment — packet §1); UNPORTED 7 → 0.
  Archived: `context/phase3/reports/2026-08-16-b8-gate.json`.
- **Terminal UNPORTED-probe re-anchor** (packet §5.3 a–c, the
  `b6-packets.md:1033` retirement duty, landed IN the flip commit):
  (a) `RunnerDeps` gained an injectable `batchStatuses` table
  (defaults to the shipped `BATCH_STATUS`); the runner/batch-status
  UNPORTED-path tests now inject a SYNTHETIC pending table over the
  NON-CORPUS module-known name `oauth_flow.build_authorize_url`
  (fictional pending fixture lives only inside the tests, never in the
  shipped table); (b) shipped-table tests re-anchored to the terminal
  assertions — `pendingEntries == []`, full-corpus prefix coverage
  still total, and a new test asserting every corpus api name
  (measured + setup) resolves `done`; (c) the Risk-8 assert took its
  terminal form — the cli gate-checkpoint test now asserts
  `skipped_unported == 0` and `passed == total` over the full corpus.
- **Checks**: `npm run check` green post-flip and post-cleanup at the
  final TS HEAD (typecheck ×5, eslint incl. the R9.1 purity boundary —
  core still imports no `node:*`/`process.env`; R9.2: `packages/node`
  does, by design — prettier, **9,833 tests / 233 files**,
  browser-bundle smoke), and `npm run conformance` re-verified
  3,251/0/0 at the same HEAD. Python repo: docs/notes/report commits only —
  no Python source touched anywhere in B8 (`just check` not triggered;
  the support-branch tree carries no `src/` or `conformance/` CODE
  change from this batch — the referee handoff regeneration was
  byte-identical and not re-committed).

## Oracle probe + differential regression (P3-2e item 3 / P3-7)

- **Oracle probe**: `oauth_flow.refresh_tokens` is a WIRE api name —
  exempt from the mechanical oracle probe (playbook P3-2e item 3; wire
  names have no `oracle.call` surface). **B8 registered ZERO new oracle
  families** (auth has no cross-language fuzz bridge — playbook Risk 7;
  compensating controls = full Layer-3 translation of every §2.3/§3.3/
  §4.3 file, the DOUBLED BLIND review below, and the four R10.9
  harnesses — two of which ran direct CPython differentials).
  `conformance/differential/strategies.py` untouched by any B8 commit
  (verified via `git log`); cumulative surface stays **55 families**.
- **Differential full-suite regression** (fresh seed + replay of EVERY
  prior gate seed, ≥500/family, oracle-py ↔ oracle-ts): RUN record
  appended to `conformance/differential/oracle/RUN.md` (B8 gate
  section) — numbers: fresh **419393897** + replays **3343231** (B2),
  **28631260** (B0), **52794688** (B0), **40075993** (B3), **53062695**
  (B4), **47824574** (B5), **628997442** (B6), **715310894** (B7) —
  9 seeds total; **28,091 examples / 0 skips / 0 divergences per seed,
  all nine; exit 0, status `ok`, no repros written.** Under-500
  families: only the two documented finite-domain exhaustions
  (`build_date_range_family` 101, `build_time_section_family` 485).
  Bridges: oracle-py 0.2.1 @ support branch, oracle-ts 0.0.0 @ `main`
  (post-flip `b59567c`), both `source_commit 70c904dc598d…`,
  protocol 1.1. `repros/` unchanged (the two RESOLVED P2-9 records).

## Referees (P3-7 — full-corpus CLOSE-OUT SWEEP)

B8 touches no bookmark source (packet §5.5 predicted "no referees"),
but the gate directive ran BOTH as the corpus-closing sweep:

- **(a) ajv draft-04 runner feed** (`npm run referee:bookmark`): 9/9
  tests green — feed + pin-exactness asserted in-test; the only REJECTs
  are the pinned EXPECTED-AND-DISCLOSED `dataGroupId` int-threading set
  (R10.7, frequency-filter precedent).
- **(b) bookmark_parser round-trip** (analytics checkout, READ-ONLY):
  handoff regenerated **BYTE-IDENTICAL** (314 entries — no drift since
  B6); selftest controls passed for BOTH oracles first; structural
  **314/314 ACCEPT**; deep **123 ACCEPT / 2 REJECT /
  189 SKIP_NON_INSIGHTS** — the 2 standing frequency-filter true
  positives only (exit 1 by design). Fresh reports identical to the
  committed `last-run-{structural,deep}.json` modulo `runtime_seconds`
  (not re-committed).
- **No NEW reject on either referee — nothing to triage.** Referee (c)
  stays CI-passive.

## R10.9 RUN records (mirrored from the shard notes; `throwaway/b8-*`
removed by this gate after BOTH arbiter sign-offs — packet §5.7 + the
two resolutions' cleanup-extension duties)

### B8-MAPFIX (`throwaway/b8-mapfix/`, deleted)

```
org-order-fuzz:    examples 1000 (>=500) divergences 0 seed 20260816
org-order-py-diff: 1000 cases (naming 600, workspace 400) through LIVE
                   CPython (py_driver.py) — divergences 0
red run: naming-order.test.ts at pre-fix main 9fb09ef — 8 failed / 1 passed
```

### B8-N1 (`throwaway/b8-n1/`, deleted)

```
io-config-probes:  74 checks, 0 failures (crash-window fault injection,
                   0600/0700, mode-guard zero-FS-touch, symlink matrix,
                   duplicate-add ConfigError, workspace-value gates)
io-fuzz + config-model-fuzz: fast-check 1000 + CPython differential 1000,
                   0 divergences, seed 20260816
swap-in run:       accounts-namespace-real.test.ts (B7 fake-backed suite
                   over the REAL on-disk config source) — 48/48 PASS
```

### B8-N2 (`throwaway/b8-n2/`, deleted)

```
refresh-probes: 77 checks, 0 failures (classifier branch matrix, TTL truth
                table ±1s, refresh-half sentinel sweep)
fs-probes:      53 checks, 0 failures (0600/0700 + no-tmp-strays, symlink
                refusals, resolver sweep, rotation-KEEP, bridge round-trips,
                MeCache TTL/chmod-ConfigError, sentinel-free errors)
fuzz:           5/5 surfaces zero-divergence, seed 20260816, 500 runs each
                (refresh classifier / storage paths / bridge resolution
                order / MeCache TTL / quote_plus vs CPython urlencode)
```

### B8-N3 (`throwaway/b8-n3/`, deleted)

```
probes: port-conflict fallback matrix + PKCE + DCR branch tables + login
        state machine + e2e loginUnified over the REAL bag (tmp HOME:
        0o700 dir, 0o600 tokens, config, me.json, DCR persist,
        accountDirExists orphan guard) + CRED-F3 redaction rows
fuzz:   4 surfaces, 0 divergent, seed 20260816, 500 runs each (pkce vs
        sha256/base64url mini-model, parseqs round-trip, paste parser,
        authorize-url round-trip)
```

All four harnesses were re-run/reproduced from the recorded seeds by the
review pairs (P3-2d item 5) — reproduction confirmed in all four reviewer
files; the pair-B arbiter additionally re-ran the atrest probe suite (62
checks, 0 failures) BOTH before and after the F1/F2 fixes.

## DOUBLED BLIND review convergence summary (P3-3 auth doubling)

Protocol: two independent pairs (4 reviewers) + per-pair arbiter; pair B
BLIND (Python sources + TS diff only; the file-access prohibition held —
verified by both the pair-B review files' citation audit and the arbiter).
Verdicts: **GO from all four lenses; both arbiters GO.** Findings: pair A
2 MAJOR + 6 minor (7 fixed red-first, 1 disclosed as class → Discrepancy
#14) at `92a5f8a`; pair B lens-1 GO with 4 non-blocking observations,
lens-2 4 findings (1 MAJOR + 3 minor: 2 fixed red-first AS CLASSES with
byte parity, 1 sanctioned deviation → Discrepancy #15, 1 docs correction
→ the #14 example fix) at `e44bea2`.

**The doubling earned its cost — DISJOINT MAJORS** (pair-B arbiter's
convergence note, quoted disposition): pair A's SEM-F1 (bridge startup
materialization unreachable from any default node composition) is a
WIRING defect no cross-language differential could see pre-fix; pair B's
F1 (pydantic-lax numeric-epoch `expires_at` accepted by Python at the
resolver read + bridge tokens parse, rejected by TS — plus TS internal
inconsistency with its own legacy-storage lax mirror) is a VALUE-DOMAIN
defect invisible to source-vs-source lenses (no Layer-3 Python test feeds
an epoch `expires_at`). **Single-pair review would have shipped one of
the two.**

**Independent convergences** (agreement = evidence, not echo): the
except-clause error-class discipline (pair A forced the alignment →
rulebook **R11.8**; pair B's blind matrices reproduced the aligned
classes field-for-field); the Discrepancy #14 `\d`-narrowing class from
opposite directions (pair A disclosed it at the bridge gates; pair B
blind-probed BOTH gate families e2e and caught the over-claimed resolver
example — F4, playbook corrected: the resolver's `/^\p{Nd}+$/u` gate is
CORRECT and must NOT be "aligned" to ASCII); the CRED-F3 posture (pair
A's assertions lens and pair B's at-rest lens independently signed off on
the same 4-site reveal allowlist, the 0600 atomic protocol, and
sentinel-free error surfaces); byte-parity writer shapes (pair B's
goldens forced `Z`-suffix parity at three writer sites → rulebook
**R11.9**, sibling to R11.8 — together they pin error classes on the way
in and byte shapes on the way out).

## Credential-safety record (CRED-F3 reveal-site allowlist after B8)

On-disk plaintext appears ONLY at (N2 notes §5, arbiter-verified by both
pairs; N3 added ZERO new reveal sites):

1. `packages/node/src/auth/token-payload.ts` `tokenPayloadBytes` —
   `tokens.json` (per-account rewrite + `TokenStore.writeTokens` +
   bridge materialization).
2. `packages/node/src/auth/storage.ts` `saveTokens` — legacy v2
   `tokens_{region}.json` (`storage.py:469-476` twin).
3. `packages/node/src/auth/bridge.ts` `serializeBridge` — bridge file
   (v2 trust boundary by design; `bridge.py:278-311` twin).
4. `packages/node/src/config-writes.ts` (`_account_to_block` twin) —
   TOML secrets.

`me.json` carries no Secret-typed material; `OAuthClientInfo` is not
Secret-bearing. Round-trip locks (write→read reveal equality) landed as
MANDATORY Layer-3 (`secret-roundtrip.test.ts` + the N2 §3.6-5 rows). No
`**********` mask is persisted anywhere (a persisted mask was the pair-B
BLOCKING criterion — zero hits). The B7 core allowlist (5 `reveal()`
sites) is unchanged.

## Discrepancies, rulings, Phase-4 ledger

- **Discrepancy #13 CLOSED — FIXED** (gate §5.6 follow-through, this
  docs commit): the 2026-08-16 user ratification superseded the
  B7-ARB-A R2 exclusion; B8-MAPFIX (`597ef7d`) made the three
  `MeResponse` container fields insertion-ordered `ReadonlyMap`s via
  the lossless-layer `LOSSLESS_KEY_ORDER` sidecar — first-org pick,
  project listing order, picker ties, and `resolveWorkspace`
  tie-breaks now match Python dict order exactly. Naming fuzz-domain
  ascending-id exclusion REMOVED; the optional order-insensitive-
  comparison HUMAN-CALL is MOOT for the first-org site (and no new
  evidence arrived on the residual #9/#10-site question — still open,
  optional, non-blocking).
- **Discrepancy #14** (pair-A SEM-F5, example list CORRECTED by pair-B
  F4): `\d`-gate ASCII narrowing at the B8 `bridge.py` `project`-field
  twins ONLY — Nd-digit project ids rejected (coded) on the TS side,
  never wrongly accepted; packet caution #1 mandates the literal
  spelling; the B7 resolver site does NOT belong to the class.
- **Discrepancy #15** (pair-B F3): default config path captured at
  module import in Python vs `ConfigManager` construction in TS —
  sanctioned call-time deviation (R10.7 disclose option), JSDoc at
  `config.ts` `defaultConfigPath`.
- **Rulebook amendments filed (R10.4)**: **R11.8** (except-clause
  error-class mapping — 8 recurrences) by the pair-A arbiter; **R11.9**
  (pydantic-lax datetime twins + writer formatter table — binds B9's
  browser CredentialStore too) by the pair-B arbiter.
- **Phase-4 burn-in ledger lines** (carried per the resolutions):
  (1) `flow.ts:898` `response_data` carries the full 200 token payload
  into refresh-error details — verbatim `flow.py:596-605` parity;
  re-examine only if a live IdP ever returns secrets the error surface
  should not carry (pair-B lens-1 O1). (2) Sanctioned TOCTOU residue of
  the R9.2 fd-hardening drop (documented in the `io-utils.ts` header +
  N1 notes) — re-examine only if burn-in surfaces a practical exploit
  path. (3) The standing #6/#7/#11/#12/#14/#15 class re-examine
  triggers, unchanged.
- **`expires_at` rendering is now vector-locked contract** (packet
  §0.3.2): Python `datetime.isoformat()` `+00:00`, no fractional digits
  at µs==0 else exactly 6 — the `token.ts` TODO(port) is CLOSED (repo
  grep: zero `TODO(port)` in `packages/node`, marker gone from
  `token.ts`).
- **Open R10.7 items carried forward (unchanged)**: frequency-filter
  clause shape + dataGroupId int threading — both await a Python-first
  fix + re-extraction; neither blocks B9.
- **Escalations: none.** All three shards + MAPFIX fable first-attempt
  green (zero P3-3 escalations); both R10.4 threshold crossings were
  handled by the arbiters as amendments (R11.8/R11.9), not stops; the
  B7 watch item (falsy-`or`) did not recur.

## §0.2 mapping (recorded per the packet's done-criteria)

The playbook P3-6 sketch binned all of `flow.py` under N3; the packet
moved the REFRESH half of `flow.py` — and with it the 7
`oauth_flow.refresh_tokens` vectors, the binding, and the `token.ts`
`expires_at` closure — into **N2**, because
`OnDiskTokenResolver._refresh_and_persist` (`token_resolver.py:174-243`)
constructs `OAuthFlow` directly; the dependency chain ran strictly
forward N1 → N2 → N3 (`flow.ts` shared N2/N3, sequential dispatch, no
merge point). Executed exactly as recorded — no scope change.

## Deferral audit (inbound ledger CLOSED; outbound handed to B9/Phase 4)

Inbound (`b7-packets.md` §7 outbound + B7 arbiter resolutions +
`b6-packets.md` residue + packet §8) — **ALL CLOSED**:

- `UNPORTED_AUTH_SEAMS` implementations (all 9 constant entries incl.
  `readSecretStdin`) + `tokenStore.accountDirExists` (B7-ARB-A SEM-F2)
  + `persistActive`/`UNPORTED_RESOLVER_SEAM` residue +
  `UNPORTED_FILE_READ_SEAM` (`nodeReadFile`, W7-D1): the committed
  §4.4 sweep test (`packages/node/test/auth-effects-bag.test.ts`,
  6 tests) instantiates `createNodeAuthEffects()` against tmp-dir
  state and asserts ZERO `UNPORTED_AUTH_SEAM` /
  `UNPORTED_RESOLVER_SEAM` / `UNPORTED_FILE_READ_SEAM` throws across
  every constant name — re-run green at this gate. The
  `unportedAuthSeam` helper + constant STAY in core (core-alone
  posture, as designed).
- Node-level default wiring: ready-made `accounts`/`session`/`targets`
  namespaces + `loginUnified` + `createNodeAuthEffects` + default
  `ResolverSources` exported from `packages/node/src/index.ts` —
  closes the four Phase-2 `__all__` deferrals at node level.
- CRED-F3 serialization rule + round-trip locks (B7-ARB-B) — landed
  (allowlist above).
- FR-045 promotion layering (B-E2E-N1) + duplicate-name plain
  `ConfigError` (B-E2E-F1) — landed in N1 with the layer-lock tests.
- `TestBridgeTokenMaterialization`, the ASR-F4c named re-take,
  `test_042_edge_cases.py::{TestTokenResolverMalformed,
  TestBridgeEdgeCases, TestConfigManagerEdgeCases}` — translated (N2/N1
  per packet §3.3/§2.3).
- UNPORTED-probe pattern retirement at the LAST flip — executed in the
  gate flip commit (§5.3 spec, terminal re-anchor above).
- Deferral headers ZEROED: repo-wide grep over `packages/{core,node}`
  test headers finds no open "→ B8" rows — only historical citations
  (Caution #18 check, re-run at this gate).

Outbound (packet §8, for the B9 packet author / Phase 4) — unchanged:
PKCE RFC 7636 rows re-translate against WebCrypto (B9); browser
`CredentialStore` + redirect PKCE + R9.3 SA refusal with
`oauth-constants.ts` copy-with-cite (B9); **B9-gate expectation already
satisfied at B8 — the B9 gate must HOLD 3,251/0/0 while adding tests
only**; the Phase-4 burn-in ledger lines above; live auth scenarios
(Phase 4, plan §6).

## Gate commits

- TS `main`: `b59567c` (flip + terminal re-anchor + report checkpoint)
  + `4095f46` (cleanup: throwaway/b8-* removal after both arbiter
  sign-offs, incl. the pair-B/arbiter dirs and the pair-A probe file
  per the two resolutions' cleanup extensions; untracked `.DS_Store`
  noise dropped per B8-ARB-B O4; `npm run check` green at HEAD).
- Python support branch: this file + report JSON + playbook
  Discrepancy #13 closure + `differential/oracle/RUN.md` B8 section +
  the 9 seed JSONs (all four shard-note files were already committed
  by their tasks).
