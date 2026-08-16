# B7 review — Pair A, Lens 2: ASSERTION FIDELITY (+ coverage)

**Reviewer**: pair-A lens-2 (adversarial, doubled-review protocol, `b7-packets.md` §5).
**Date**: 2026-08-16. **Scope**: BOTH shards (per the orchestrator's batch-level ruling) —
B7-A2 (`64542e1`, resolver core + region probe) and B7-A1 (`e34d218`, namespaces +
login_unified + naming + ResolverSeams), TS repo `main`; Python arbiter at
`ts-port/phase2-contract-support` (b7-packets @ `f492a4e`, shard notes @ `04e2f23`/`b8baee5`).
**Method**: R10.2 name-and-body diff of every translated test file against its Python
original (both B6 ledger files included), header-exclusion audit, test-count
reconciliation, PBT-arbitrary domain check, binding-honesty read of `wire-auth.ts`,
independent 14-vector replay, harness RUN reproduction from recorded seeds, R9.1
purity grep, live-CPython verification of the A2 Nd/isdigit disclosure.

## 1. Mechanical verifications (all reproduced by this reviewer)

| Check | Result |
|---|---|
| 14-vector replay (`npm run conformance`) | **3,251 → 3,244 PASS / 0 FAIL / 7 UNPORTED** (corpus @ `70c904dc598d`) — exact §2.8 pre-flip shape; bundle ids = the 14 ids of packet §2.3, 1:1 |
| R9.1 purity grep (`process.env`, `node:` over `auth/resolver.ts`, `auth/region-probe.ts`, `accounts/*`, `workspace.ts`) | clean — every hit is a comment/JSDoc; `eslint .` green; `tsc --noEmit` green ×all workspaces |
| Full Layer-3 suite (`npm run test`) | **9,368 passed / 7 skipped** — matches the A1 commit message |
| A2 harness re-run (recorded seeds 20260816 / 20260817) | `resolver-truth: checks 788, failures 0, fuzz-divergences 0` · `probe-branches: checks 660, failures 0, fuzz-divergences 0` — byte-identical to RUN.md |
| A1 harness re-run (seed 20260818) | `namespace-branches: checks 352, failures 0, captured-errors 72` · `ops-fuzz: sequences 600, ops 3676, divergences 0` — byte-identical to RUN.md |
| `prettier --check` | fails ONLY on two UNTRACKED reviewer scratch files (`throwaway/review-a2-{err,truth}.ts` — another review agent's, not in either B7 commit). The committed tree is clean. Not a B7 finding. |

**Binding honesty (`conformance-runner/src/wire-auth.ts`) — CONFIRMED.** The binding
calls the REAL exported `probeRegion` with the REAL `probeClientFromFetch`
(`https://test.invalid`, the Python fixture's base); the `RecordingCallback` stub only
logs regions; the binding never fetches, never classifies errors, never assembles
attempts; absent kwargs are omitted so library defaults apply; result mapping is a
mechanical `{region, attempts}` tuple→array encode. Anchors: `batch-status.ts:111`
still `["region_probe.", "pending"]` (flip left to the gate ✓);
`batch-status.test.ts:86-89,240-243` anchors intact ✓; `runner.test.ts` /
`oracle-protocol.test.ts` re-anchored to `oauth_flow.refresh_tokens` — a disclosed
pull-forward of gate duty §4.3 (A2 RUN disclosure 4, B6-BIND precedent).

## 2. Test-count reconciliation (Python `def test_` vs TS `it`/`it.each`)

### Shard A2

| Python source (count) | TS file (count) | Verdict |
|---|---|---|
| `test_resolver.py` (31) | `resolver.test.ts` — 31 same-named + 8 spec-cited additions (W1-code guard lock; "packet §2.2 byte-for-byte rules" describe ×7) | 1:1, no drops |
| `test_resolver_pbt.py` (5) | `resolver.pbt.test.ts` (5, same names) | 1:1; strategy shapes preserved (`[a-zA-Z0-9_-]{1,12}`, `^[1-9][0-9]{0,9}$`, 1..2³¹−1); substitutions header-cited |
| `test_region_probe.py` (16) | `region-probe.test.ts` — 16 same-named + 2 additions (`probe_region_for_credential` guards, registry-audited-out per §2.3 coverage note) | 1:1; body diffs faithful (see §3) |
| `test_042` `TestAccountNameBoundaries` (3, incl. 9-param parametrize) | `account-edge.test.ts` (3; `it.each` carries all 9 identical params) | 1:1 |
| `test_042` `TestOAuthTokenValidatorUnderCopy` (2) | `account-edge.test.ts` (2) | 1:1; `model_copy`→spread pin header-cited per packet §2.4 |
| `test_042` `TestSessionReplaceSentinel` (5) | `session-replace.test.ts` (5) | 1:1; sentinel semantics (null-clears vs omitted-preserves) asserted identically |
| `test_042` `TestResolverEdgeCases` (4, incl. 4-param parametrize) | `resolver.test.ts` (4; `it.each` all 4 params, `match="MP_WORKSPACE_ID"` → `toContain`) | 1:1 |
| `test_session_pbt.py` (9) | `session-replace.pbt.test.ts` (9, same names incl. the TypeAdapter roundtrip — translated, not duplicate-cited, header note per the §2.4 "either way" rule) | 1:1 |

### Shard A1

| Python source (count) | TS file (count) | Verdict |
|---|---|---|
| `test_accounts_namespace.py` (62) | `accounts-namespace.test.ts` (44) + `login-unified.test.ts` (16) = 60 | 60 translated 1:1 per class; **2 accounted deviations** — see Findings 1–2 |
| `test_session_namespace.py` (6) | `session-namespace.test.ts` (6) | 1:1 |
| `test_targets_namespace.py` (15) | `targets-namespace.test.ts` (15) | 1:1 |
| `test_login_region_check.py` (4) | `login-region-check.test.ts` (4) | 1:1 (E-2 raise, no-tokens-persisted atomicity, match-ok, no-domain back-compat) |
| `test_naming.py` (13) | `naming.test.ts` (14 = 13 + the Caution-#12 pre-truncation-ASCII invariant the packet MANDATES) | 1:1 + required addition |
| `test_naming_pbt.py` (8) | `naming.pbt.test.ts` (8) | 1:1; category-filter substitution for `st.characters(whitelist_categories)` header-cited; org-id leading-zero domain nudge inline-cited (int() roundtrip) |
| `test_workspace_use.py` B7 rows (5 classes = 11 tests + 4 individual W1-deferred cases) | `workspace-use.test.ts` (11 + 4 in "B7 de-deferred" describe) | 1:1 over REAL `resolverSeamsFromEffects`; env-set-after-construction ordering preserved |
| `test_workspace_init.py` (`TestActiveResolution` 1, `TestExplicitOverrides` 3, `TestTarget` 2) | `workspace-init.test.ts` (6 + the 3 constructor WS1 rows from `test_workspace.py:969-1021`) | 1:1; `TestBridgeTokenMaterialization` correctly left B8 in the header |
| `test_workspace.py::TestCredentialResolution` | header note in `workspace-facade.test.ts:10` | class body is EMPTY in Python (B1 Fix 10) — verified at `test_workspace.py:96-104`; nothing to port, correctly recorded |
| `test_042` `TestSecretLeakage` (4) | `secret-redaction.test.ts` (4) | 1:1; the on-disk-tokens case re-expressed over the injected `tokenResolver` exactly as packet §3.4 sanctions (residual: the real missing-tokens→OAuthError branch is B8-N2's, see Observation c) |
| `test_workspace_oauth.py` (5) | `workspace-oauth.test.ts` (5) | 1:1 |
| `test_workspace_resolution.py::TestMeServiceResolveWorkspace` (5) | `me-service.test.ts` (2 translated + 3 duplicate-cited) | the 3 citations verified against the pre-existing dagger-path describe — genuinely equal-or-stronger (cold-cache asserts zero client calls, matching `api.me.assert_not_called`) |
| `test_workspace_resolution.py::TestFacadeResolverWiring` (4) | `workspace-facade.test.ts:706` (4) | 1:1; the B4-C1 stale header in `client-workspace.test.ts:9-17` corrected in the same commit (Caution #17 ✓) |

**Header-exclusion audit**: every excluded/merged/duplicate-cited case carries a
file-header citation to the packet or plan D4; deferral headers list ZERO remaining
B7 rows (Caution #18 ✓ — checked `workspace-use.test.ts`, `workspace-init.test.ts`,
`workspace-facade.test.ts`).

## 3. Assertion-strength spot checks (body-level diffs)

- `region-probe.test.ts`: error-path quartet byte-faithful — attempts order/status/
  body asserts identical; the network-error body keeps **Python's own loosened OR
  assert** (`test_region_probe.py:167`) with citation, exactly as packet §2.3 item 5
  requires (no tightening, no loosening). Body-cap tests use the same 100 KB "x"
  fixture (ASCII ⇒ UTF-16 length == codepoints; the surrogate-straddle boundary is
  pinned in the harness at 4096 as §2.6 item 8 requires). URL-stripping class:
  monkeypatch-spy substitution header-cited and STRONGER than Python (adds a real
  `probeRegionForCredential` recording-fetch observation).
- `resolver.test.ts` `TestAccountAxisPriority`/edge classes: same env bags, same
  fixture accounts, same winner asserts; `isinstance(ServiceAccount)` →
  discriminant-tag check (the union has no runtime class — mechanical).
- `accounts-namespace.test.ts` `TestTest`: `error_code`/`error_details` asserts match
  Python exactly (`error_details is not None` + `"attempts" in` → `not.toBeNull()` +
  `Object.hasOwn`); the SA-monkeypatch → browser-tokenResolver injection substitution
  is inline-cited and exercises the same broad-catch (in TS the transport normalizes
  every fetch rejection, so the resolver seam is the only faithful non-library leak
  site — the substitution note is correct).
- `workspace-use.test.ts` de-deferred classes: full-assert parity incl. the
  FR-017 target-env-override secondary asserts (account/workspace still from target)
  and the persist-clears-stale-workspace disk assert.
- `naming.test.ts` `test_first_org_wins_when_multiple`: same ascending-id fixture,
  same expected value; the insertion-vs-ascending divergence is NOT self-sanctioned —
  disclosed inline + ESCALATED in `B7-A1-notes.md:71-79` (Caution #13 ✓).

## 4. Resolver-precedence PBT — full-chain coverage check (lens mandate)

- `resolver.pbt.test.ts` mirrors Python's **5 properties only** (bridge always null,
  no target, one env var at a time) — this is exactly what packet §2.4 prescribes
  ("same strategy shapes"), so it is NOT an R10.2 violation.
- The FULL chain (env > param > target > bridge > config) is covered in
  `throwaway/b7-a2/resolver-truth.ts`, which I verified generates **all source
  combinations**: exhaustive bitmaps (account 2⁶ = 64 through `resolveAccountAxis`;
  project 2⁴ × 3 account states = 48; workspace 2⁵ = 32 through the full
  `resolveSession`) + a 15-boolean-dimension `fc.record` fuzz (600 runs, seed
  20260816) through the REAL `resolveSession` diffed against an independent
  `firstPresent` mini-model — env-SA/env-OT/explicit/target/bridge/active all
  independently toggled per axis, plus the WS1 guard and both no-account/no-project
  error rows. Zero divergences, reproduced. The RUN-table label "2^4 × 3" for the
  project axis is a sensible re-binning of the packet's overlapping "2^5 × 2"
  enumeration (account-default cannot be both a bitmap bit and an account state);
  coverage is equivalent — no combination lost.
- See Finding 3 for the persistence caveat (the harness is gate-deleted).

## 5. Independent verification of the A2 §2.2 disclosure (live CPython)

Reproduced with `uv run python` against the arbiter repo:
`MP_PROJECT_ID="٤٢"` (Arabic-Indic Nd) **RESOLVES** with `project.id == '٤٢'`
(packet §2.2's claimed two-stage Nd failure does not exist);
`MP_PROJECT_ID="²"` (Numeric_Type=Digit, non-Nd) raises
`ConfigError: Invalid project ID: '²'. Must match ^\d+$` (second stage). The A2
disclosure is therefore ACCURATE; the residual TS divergence ("²" fails the TS guard
with the env-var message instead of the model message — same class, same code) is
correctly escalated to the arbiter with a `TODO(port)` rather than self-sanctioned.

## 6. Findings

**F1 (minor, process — packet-text deviation, well-cited).**
`TestSummaryTableDynamicWidth::test_long_name_is_not_truncated`
(`test_accounts_namespace.py:967-991`) is EXCLUDED by the implementer
(`accounts-namespace.test.ts` header + `B7-A1-notes.md:29`) citing plan D4, but
packet §3.4 row 1 says "ALL 17 classes" and lists the class as TAKEN — the packet's
only recorded exclusion is `TestCliExitCodes`. The exclusion is substantively
defensible (the test imports and drives `cli.commands.account._format_summary_table`,
a CLI renderer — verified in the Python source), and the header/notes citations
satisfy the audit rule, but it is an implementer-made scope call on a packet-listed
class. **Ask**: arbiter ratifies the exclusion explicitly (the same way §3.4
ratified `TestCliExitCodes`), so the ledger shows an arbiter decision rather than an
implementer deviation.

**F2 (observation, no action needed).** `TestPublicSurface` (2 Python tests) folded
to 1 TS test asserting all 13 `__all__` names resolve on the namespace object —
header-cited ("module `__all__` has no TS runtime analog"); the merged assert
subsumes both originals (`login`/`test` are among the 13). No strength lost.

**F3 (minor, advisory — coverage persistence).** The only full-precedence-chain
fast-check coverage (exhaustive truth table + 600-run fuzz, §4 above) lives in
`throwaway/b7-a2/`, which gate step §4.6 DELETES; the surviving artifacts are the
RUN mirror in `B7-A2-notes.md` and the deterministic Layer-3 examples
(`TestCrossSourceOrdering` ×12 + the §2.2 rule-lock describe). This is
packet-conformant, but under the no-second-oracle posture the batch loses its only
randomized full-chain lock at the gate. **Ask**: arbiter decides before gate
cleanup whether to promote `resolver-truth.ts` (or a slimmed fc property over the
15-dim source bag) into `packages/core/test/auth/` as a permanent test; cost is
near-zero since the file already passes under vitest semantics.

**F4 (observations, verified accurate, arbiter action items already queued).**
(a) Nd/isdigit disclosure — independently confirmed (§5); needs the arbiter ruling
the notes request. (b) Caution #13 first-org-order — escalation present and
properly not self-sanctioned. (c) `TestSecretLeakage`'s 4th case is now
propagation-only (the fake resolver supplies the OAuthError); the real
missing-tokens→OAuthError branch rides with B8-N2's `OnDiskTokenResolver` — already
in the §7 outbound ledger, no new entry needed, but B8's packet author should treat
`test_session_to_credentials_oauth_browser_missing_tokens_raises` as a named
re-take. (d) Pending-exemplar re-anchor pull-forward — disclosed, batch-status
anchors verified intact for the gate.

**No CRITICAL or MAJOR findings.** No silent assertion drops, no un-cited
loosenings, no fabricated coverage found in either shard. Every mechanism
substitution I diffed traces to a packet-sanctioned rule with a file-header
citation.

## 7. Per-shard coverage statement (for the arbiter's record)

- **A2 reviewed under lens 2**: resolver.test.ts, resolver.pbt.test.ts,
  region-probe.test.ts, account-edge.test.ts, session-replace.test.ts,
  session-replace.pbt.test.ts, wire-auth.ts (binding honesty), throwaway/b7-a2
  (RUN reproduction + arbitrary-domain audit), 14-vector replay, purity grep.
- **A1 reviewed under lens 2**: accounts-namespace.test.ts, login-unified.test.ts,
  session-namespace.test.ts, targets-namespace.test.ts, login-region-check.test.ts,
  naming.test.ts, naming.pbt.test.ts, secret-redaction.test.ts,
  workspace-use/init/facade/oauth.test.ts, me-service.test.ts,
  client-workspace.test.ts header fix, throwaway/b7-a1 (RUN reproduction),
  purity grep over `accounts/*` + `workspace.ts`, full-suite + `npm run check`
  components re-run.
