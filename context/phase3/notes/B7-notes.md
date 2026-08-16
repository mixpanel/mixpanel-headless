# B7 batch notes — accounts/session/targets + resolver core + region probe (gate record)

**Status**: B7 GATE CLOSED · 2026-08-16 · fable, ≤ high (task B7-GATE,
P3-2e). Packet: `context/phase3/design/b7-packets.md` §4 (flip spec).
Shard notes: `B7-A1-notes.md`, `B7-A2-notes.md` (RUN records mirrored
below). Reviews (DOUBLED per P3-3 — two independent pairs + per-pair
arbiter): `b7-reviewA-{semantics,assertions}.md` +
`b7-reviewA-resolution.md` (fixes `4c8946a`);
`b7-reviewB-{credentials,e2e}.md` + `b7-reviewB-resolution.md`
(fixes `1151e86`). Both resolutions: **GO**.

## Gate checkpoint (P3-2e items 1–2)

- **Flip**: `batch-status.ts` `region_probe.` → `done` (TS gate commit
  on `main`; the flip + report checkpoint land in the same commit per
  P3-2e item 1). `oauth_flow.` (B8) is now the ONLY pending prefix.
- **Standing collision assertion** (recorded scan, corpus pin
  `70c904dc`, measured + `call.setup[]` apis): the only corpus api
  name matching the flipped prefix is `region_probe.probe_region`
  (×14); the only still-pending corpus api name is
  `oauth_flow.refresh_tokens` (×7), not prefixed by any `done` entry.
  Zero collisions — as predicted by packet §4.1.
- **Conformance report**: `npm run conformance` →
  **3,251 vectors — 3,244 PASS / 0 FAIL / 7 UNPORTED** @ corpus
  `70c904dc598d`. Attribution: PASS +14 over the B6 baseline (3,230)
  = exactly the B7 gate delta (the 14 `region_probe.probe_region`
  vectors, bound at B7-A2 and passing-while-pending since the shard
  commit; no P3-1 † adjustment — none of the 14 carries `call.setup[]`
  or `call.session`, packet §1); UNPORTED 21 → 7 = the remaining
  `oauth_flow.refresh_tokens` (B8). Archived:
  `context/phase3/reports/2026-08-16-b7-gate.json`.
- **Anchor re-pins** (packet §4.3): `batch-status.test.ts`
  pending-prefix anchors + the `runVector` pending-anchor re-pinned to
  `oauth_flow.refresh_tokens` in the flip commit (a new B7-flip test
  additionally asserts exactly ONE pending entry remains);
  `runner.test.ts` + `differential/test/oracle-protocol.test.ts` had
  been re-anchored at B7-A2 bind time (A2 disclosure 4 — bound-name
  anchors break at BIND, status anchors at the FLIP). The pattern
  retires at the B8 gate (`b6-packets.md` §12.5).
- **Checks**: `npm run check` green post-flip (typecheck ×5, eslint
  incl. the R9.1 purity boundary — no `node:*`/`process.env` in core —
  prettier, **9,387 tests / 212 files**, browser-bundle smoke).
  Python repo: docs/notes/report commits only — no Python source
  touched anywhere in B7 (`just check` not required per packet §4.5;
  the support branch tree carries no `src/` or `conformance/` code
  change from this batch beyond the gate's `RUN.md` append + report
  archive).

## Oracle probe + differential regression (P3-2e item 3 / P3-7)

- **Oracle probe**: `region_probe.probe_region` is a WIRE api name —
  exempt from the mechanical oracle probe (playbook P3-2e item 3;
  wire names have no `oracle.call` surface). **B7 registered ZERO new
  oracle families** (auth has no cross-language fuzz bridge — playbook
  Risk 7; compensating controls = full Layer-3 translation + the
  DOUBLED review below + the two R10.9 local-mini-model harnesses).
  `conformance/differential/strategies.py` untouched by B7 (verified:
  no B7 commit touches it; cumulative surface stays 55 families).
- **Differential full-suite regression** (fresh seed + replay of EVERY
  prior gate seed, ≥500/family, oracle-py ↔ oracle-ts): see the
  RUN record appended to `conformance/differential/oracle/RUN.md`
  (B7 gate section) — numbers summarized here:
  - Seeds: fresh **715310894** + replays **3343231** (B2), **28631260**
    (B0), **52794688** (B0), **40075993** (B3), **53062695** (B4),
    **47824574** (B5), **628997442** (B6) — 8 seeds total.
  - Result: **28,091 examples / 0 skips / 0 divergences per seed, all
    eight seeds; exit 0, status `ok`, no repros written.** Raw JSONs:
    `2026-08-16-b7-gate-seed{715310894,3343231,28631260,52794688,40075993,53062695,47824574,628997442}.json`.
  - Under-500 families: only the two documented finite-domain
    exhaustions (`build_date_range_family` 101,
    `build_time_section_family` 485). `skipped_per_target` all-zero.
  - Bridges: oracle-py 0.2.1 @ `ts-port/phase2-contract-support`,
    oracle-ts 0.0.0 @ `main` (B7 gate tree), both `source_commit
    70c904dc598d…`, protocol 1.1.

## Referees (P3-7 — statement of the check)

**Not required at B7 and not run.** The P3-7 schedule runs referees
(a)+(b) at the B3 and B6 gates (bookmark-touching batches) and at any
other gate whose modules emit bookmark payloads. Check performed:
`git diff --name-only db8e079..HEAD` over the TS repo (all B7 commits:
A2 `64542e1`, A1 `e34d218`, ARB-A `4c8946a`, ARB-B `1151e86`, gate
flip) touches NO `bookmarks/` source, no bookmark test, and no referee
feed; B7's modules (auth resolver, region probe, accounts/session/
targets namespaces, naming) construct no bookmark payloads. Referee
(c) stays CI-passive.

## R10.9 RUN records (mirrored from the shard notes; `throwaway/b7-*`
removed by this gate after both arbiter sign-offs — packet §4.6)

### B7-A2 (`throwaway/b7-a2/`, deleted)

```
resolver-truth:  checks 788 (incl. 600 fuzz, seed 20260816)  failures 0  fuzz-divergences 0
probe-branches:  checks 660 (incl. 600 fuzz, seed 20260817)  failures 0  fuzz-divergences 0
total checks 1448 — exhaustive axis bitmaps (2^6/2^4×3/2^5), error
rows, mandatory edge set, every probe branch (§2.6), credential
branches, fc fuzz vs independent mini-models
```

The full-precedence-chain coverage is NOT lost with the deletion: it
was PROMOTED to the permanent
`packages/core/test/auth/resolver-precedence-chain.pbt.test.ts`
(12 tests, same seed 20260816 — B7-ARB-A ruling ASR-F3); the gate
cleanup verified the file is on disk and untouched by the sweep.

### B7-A1 (`throwaway/b7-a1/`, deleted)

```
namespace-branches: checks 352  failures 0  captured-errors 72
ops-fuzz:           sequences 600 (≥500)  ops 3676  divergences 0  seed 20260818
```

Error-branch enumeration (~90 rows incl. the login_unified flag
matrix, E-2/E-3/E-4/E-6/E-8, WS1 guards, force-remove orphans), all
35+ `UNPORTED_AUTH_SEAM` defaults by name, the login_unified state
machine sweep (24 runs + 3 relogin arms), edge set, and the
secret-sentinel sweep (72 captured errors × message + `toDict()`
JSON, sentinel-free — feeds the pair-B credential lens).

Both pairs re-ran/reproduced the recorded harness numbers from the
recorded seeds during review (P3-2d item 5) — reproduction confirmed
in all four reviewer files.

## DOUBLED-review convergence summary (P3-3 auth doubling)

Protocol: two independent pairs (4 reviewers) + per-pair arbiter;
pair B BLIND (Python sources + TS diff only; file-access prohibition
honored — verified by the pair-B resolution's independence note).
Verdicts: **GO from all four lenses; both arbiters GO.** Findings:
zero blockers, zero majors; pair A 3 MINOR + 3 nits (all applied at
`4c8946a`), pair B 1 MINOR code-contract fix + 2 doc-contract fixes +
2 disclosure records (all applied at `1151e86`).

**Classes BOTH pairs hit independently** (agreement = evidence, not
echo): Caution #13 org-order integer-key hoisting (pair A escalated →
ruling R2; pair B reproduced the divergence blind, byte-for-byte as
ruled); `MP_WORKSPACE_ID` > 2^53−1 coded-ConfigError mapping (ruling
R3 / packet-sanctioned, hit blind by pair-B row R33); Nd-digit env
handling (ruling R1; pair B confirmed observable parity blind);
Caution #8 reverse-table network rendering (23 paired scenario groups
pair A; `ConnectError` + `ConnectTimeout` byte-identical end-to-end
pair B); the 14-vector from-scratch replay + all RUN-seed
reproductions (both pairs, 3,244/0/7 pre-flip both times); the SEM-F1
falsiness fixes (pair A originated; pair B verified the fixed
behavior equals live Python, blind).

**Pair-B-only finds** (the doubling's justification on the
no-second-oracle batch): **B-E2E-F1** — the duplicate `accounts.add`
error CLASS lived in the seam CONTRACT (JSDoc + fake), invisible to
pair A's implementation-vs-source diff, and would have been baked
into B8-N1's real ConfigManager adapter (`ConfigError`/CONFIG_ERROR
per `config.py:446`, NOT `AccountExistsError` — fixed red-first);
**B-E2E-N1** — FR-045 first-account promotion attributed to the wrong
layer (namespace transaction, not ConfigManager); **CRED-F1/F2/F3** —
the reveal-site 1:1 audit, the empty-Secret cosmetic divergence, and
the B8 JSON-persistence foot-gun, all products of the credential lens
pair A does not run. Zero contradictions between pairs; pair B also
functioned as an independent confirmation pass over the pair-A fixes.

## Credential-safety fold-ins (pair-B gate duties)

**Reveal-site allowlist after B7** (CRED-F1; arbiter-verified 1:1
against Python `get_secret_value()` sites):

| TS `reveal()` site | Python twin | Purpose |
|---|---|---|
| `auth/account.ts:585` (`accountAuthHeader`, Phase-2) | SA header build | Basic header |
| `auth/region-probe.ts:382` | `region_probe.py:246` | SA Basic probe header |
| `auth/region-probe.ts:387` | `region_probe.py:250` | inline oauth_token Bearer |
| `accounts/accounts-ops.ts:726` | `accounts.py:844` | `login` → `freshBrowserBearer` |
| `accounts/login-unified.ts:593` | `accounts.py:1665` | `_login_unified_new_browser` → `freshBrowserBearer` |

Distinct-but-allowed plaintext surfaces (not `reveal()` sites):
`accounts.token()` returns the plaintext bearer (Python-documented
public behavior); test-side reveals in `fake-auth-effects.ts` are the
designated store writes.

**CRED-F2 (disclosure 13, carried per the pair-B resolution)**: TS
`Secret` renders `'**********'` for an EMPTY wrapped value where
Pydantic `SecretStr('')` renders `''` (live-CPython-verified).
Phase-2-owned `secret.ts`, unchanged in B7; the only B7
`new Secret("")` site is a defensive unreachable fallback
(`login-unified.ts:763`). MORE redaction, never less — no code
change. Re-examine only if a serialized bag is ever byte-diffed
against Python output containing an empty SecretStr.

## Discrepancies & escalations

- **Discrepancy #13 PASTED into the playbook** at this gate (pair-A
  ruling R2 follow-through — first-org pick / listing order for
  integer-like `/me` Record keys; the pair-B blind reproduction note
  included). The optional user HUMAN-CALL (order-insensitive
  comparison ratification for #9/#10/#13-mechanism sites) remains
  open and non-blocking.
- Standing disclosed divergences recorded at shard level (no new
  playbook entries — existing-class instances): Nd/Numeric_Type
  `MP_PROJECT_ID` guard-position split (ruling R1 —
  message/details-only, class+code identical); `MP_WORKSPACE_ID` >
  2^53−1 → coded ConfigError (Discrepancy #6/#7 family, ruling R3);
  `probeBaseUrl` origin-vs-urlunsplit skew on non-canonical inputs
  (SEM-F3, JSDoc-disclosed, unreachable via shipped consumers);
  network-error class rendering beyond the committed reverse table
  (Caution #8, vector-locked for `ECONNREFUSED`); SEM-F2 residuals
  (orphan-dir message NAME-vs-PATH, overlap-state class ordering);
  browser-flow placeholder-dir mechanism substitution (A1 disclosure
  2); empty-Secret rendering (CRED-F2, above).
- **Escalations: none.** No module task missed done-criteria (zero
  P3-3 escalations — both shards fable first-attempt green); no R10.4
  threshold crossing at B7 (the SEM-F1 falsy-`or` pattern stands at
  ONE batch recurrence; watch item for B8).
- Open R10.7 items carried forward (unchanged): frequency-filter
  clause shape + dataGroupId int threading — both await a
  Python-first fix + re-extraction; neither blocks B8.

## Deferral audit (inbound ledger CLOSED, outbound handed to B8)

Inbound (`b6-packets.md` §13 + packet §7) — ALL LANDED: the four
`ResolverSeams` real implementations (A1 `resolver-seams.ts`;
`persistActive` routing shipped, impl B8-owned as designed);
`test_workspace_use.py` resolver classes (+14 tests, header ZERO B7
rows); `test_workspace_init.py` resolver classes (+9, only
`TestBridgeTokenMaterialization` → B8 remains);
`test_workspace.py::TestCredentialResolution` (verified EMPTY in
Python — nothing to port, recorded); `test_042_edge_cases.py` B7
classes (4 → A2 files; `TestSecretLeakage` → A1;
`TestCliExitCodes` EXCLUDED per plan D4, decision recorded);
`test_workspace_resolution.py` residue (both stale-header classes
landed; `client-workspace.test.ts` header corrected); the
UNPORTED-probe re-anchor duty (split A2/gate as disclosed). Header
grep at the gate confirms zero remaining "→ B7" deferral rows in the
TS test tree.

Outbound to B8 (normative list = packet §7 + the two resolutions):
`UNPORTED_AUTH_SEAMS` implementations (config TOML writes/reads, env,
`tokenStore.*` incl. the NEW `accountDirExists` — ARB-A SEM-F2,
on-disk `tokenResolver`, `oauthFlow.login`, `bridge.*`, on-disk
`meCacheStore`, `persistActive` via `persistActiveToConfig`,
`readSecretStdin`); ready-made `accounts`/`session`/`targets` exports
+ default `ResolverSources` wiring for bare `Workspace()`;
`TestBridgeTokenMaterialization`; `test_042_edge_cases.py`
`{TestTokenResolverMalformed, TestBridgeEdgeCases,
TestConfigManagerEdgeCases}`; the named re-take
`test_session_to_credentials_oauth_browser_missing_tokens_raises`
(ASR-F4c); the SECRET SERIALIZATION RULE + write→read round-trip lock
(CRED-F3); FR-045 promotion exactly once in the adapter transaction
(B-E2E-N1); duplicate-add = plain `ConfigError` (B-E2E-F1); the
UNPORTED-probe pattern retirement at the B8 gate flip.

## Gate commits

- TS `main`: gate flip commit (flip + anchors + report checkpoint +
  `throwaway/b7-*` removal).
- Python support branch: this file + report JSON + playbook
  discrepancy #13 + `differential/oracle/RUN.md` B7 section + the 8
  seed JSONs.
