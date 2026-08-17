# B8 review — Pair A, Lens 2: assertion fidelity + seam closure

**Status**: COMPLETE · 2026-08-16 · reviewer: pair-A lens-2 (fable).
Scope: ALL B8 commits since the B7 gate — TS `9fb09ef..HEAD` = `597ef7d`
(B8-MAPFIX), `44fc912` (B8-N1), `53a134e` (B8-N2), `8017fc4` (B8-N3) — per the
orchestrator's batch-level coverage ruling (per-shard coverage recorded below:
every shard's translated files audited by name; MAPFIX audited in full).
Spec: `b8-packets.md` §6 A-lens-2; playbook P3-2(d) items 1–5. File name per
orchestrator instruction (`b8-reviewA-assertions.md`; the packet §6 spelling
`b8-review-pairA-fidelity.md` is superseded by the dispatch).

## Verdict

**GO with 1 MAJOR finding (F1, test-coverage) + 2 minor.** No blocker. No
silent assertion weakening found anywhere except F1's composition gap; seam
closure is complete (zero leftover stubs in `packages/node`); the MAPFIX is
genuine (red run independently reproduced); all 7 `oauth_flow.refresh_tokens`
vectors replay green (full-corpus 3,251/3,251 PASS self-run); core purity
boundary green.

## Findings

### F1 — MAJOR (test-coverage / R10.2 weakening): the `[settings].custom_header → bridge.headers` COMPOSITION lock did not survive the N2 split

- Python lock: `tests/unit/test_bridge_export.py::TestAccountsNamespaceWiring::
  test_export_bridge_attaches_settings_custom_header` (:275-293) asserts
  end-to-end that a header set via `ConfigManager.set_custom_header` lands in
  the exported `bridge.headers` through `accounts.export_bridge`.
- TS re-expression (`packages/node/test/bridge.test.ts:265`,
  `test_export_bridge_attaches_custom_headers`) locks only the EFFECT half —
  "a supplied headers map lands in the bridge verbatim" — and its comment
  delegates the composition to "the CALLER's composition in Python
  (`accounts.export_bridge` reads the config and passes `headers=`)".
- The TS caller composition exists (`packages/core/src/accounts/accounts-ops.ts:847-848`:
  `getCustomHeader()` → `{[header[0]]: header[1]}` → `effects.bridge.export`)
  and is correct by inspection, **but no test at any layer exercises it with a
  non-null custom header**: `packages/core/test/accounts/accounts-namespace.test.ts`
  never sets `customHeader` in the fake state for its exportBridge tests
  (grep: zero `customHeader` hits in any `packages/core/test/accounts/*.test.ts`);
  the N1 throwaway swap-in copy (`throwaway/b8-n1/accounts-namespace-real.test.ts`)
  likewise; `packages/node/test/auth-effects-bag.test.ts:138` only asserts
  `getCustomHeader()` **is null**. A name/value swap or a dropped-header
  regression at `accounts-ops.ts:847-848` passes the entire suite.
- Contrast: the sibling drop `test_export_bridge_uses_active_account_when_unspecified`
  IS properly re-covered (`accounts-namespace.test.ts:811` + the swap-in copy),
  and the settings-header → `Session.headers` path is separately locked
  (`settings-headers.test.ts` TestSettingsHeaderAttachment) — F1 is the ONLY
  composition that fell through the split.
- Fix shape (small): add one fake-backed case to the core namespace suite
  (set `state.customHeader`, call `accountsExportBridge`, assert the exported
  `headers` bag) OR extend the bag test to set a real custom header before an
  `effects`-composed export via the core `accountsExportBridge` orchestration.

### F2 — MINOR (TODO(port) triage / stale markers referencing completed batches)

`packages/core/src` still carries future-tense port markers whose work B7/B8
completed: `accounts/auth-effects.ts` (inside `unportedAuthSeam`: "TODO(port):
B8 replaces this default with the real node effect"),
`workspace.ts:1182` ("B8's node wiring supplies the on-disk …"),
`workspace-members/governance-data.ts:62,219` ("B8 wires node:fs"),
`workspace-members/lifecycle.ts:113` ("B7 replaces this default with the real
resolver"). The default-throwing seams legitimately STAY (packet §4.4
core-alone posture), but P3-2(d) item 4 requires every marker owned or fixed —
these should be rewritten to cite §4.4 ("real implementation lives in
`packages/node`; the core default documents the core-alone posture") instead
of pointing at now-landed batches as future work. Owner: B8 gate task (docs
touch, same commit as the flip). Caution-18 compliance is otherwise met:
`packages/node` has ZERO `TODO(port)`; the `token.ts` `expires_at` marker is
GONE (closed, not re-scoped); the `workspace-init.test.ts` deferral header row
is dropped with a disclosed relocation citation.

### F3 — MINOR (cosmetic header self-contradiction)

`packages/node/test/storage-paths.test.ts` header says "ALL 5 classes
translated … PYTHON-ONLY: none in this file" then correctly lists two
Python-only members (`test_check_and_fix_permissions_uses_fchmod_not_chmod`
:275, `test_windows_skip_does_not_crash` :303, both cited to the plan §4.2 /
R9.2 fd-flag drop). The citations are complete; only the "none" wording
contradicts the two exclusions that follow. Wording fix only.

## Evidence log

### E1 — R10.2 name-level reconciliation (per shard, per file)

Method: `def test_` name extraction per Python file diffed against quoted
`test_*` names in the TS twin (catches `it.each` folding that raw `it(` counts
miss; TS raw `it(` counts under-read several files — e.g. io-utils 26 `it(`
but 41 names via `it.each`).

| Python file (tests) | TS file (shard) | Coverage | Exclusions / extras — disposition |
|---|---|---|---|
| test_io_utils.py (48) | io-utils.test.ts (N1) | 41/48 + 1 rename | 7 excluded, ALL header-cited: TestDirfdWalk 4 + TestOpenCredentialFdFlags 1 (plan §2.2 + R9.2 fd-flag drop), FIFO+chardev 2 (SPLIT per packet §2.3; `test_rejects_directory_via_stat_check` added). Rename `test_is_oserror_subclass`→`test_is_mixpanel_headless_error_subclass` + fd-leak probes re-expressed as 200-rejection loops — both header-cited. `mode & 0o077` guard is the `it.each([0o644,0o660,0o604,0o666,0o777])` row incl. the caution-11 no-FS-touch assert. |
| test_config.py (51) | config.test.ts (N1) | 51/51 | +4 extras all accounted: 3 = inbound `TestConfigManagerEdgeCases` (all 3 names match test_042_edge_cases.py), 1 = NEW `test_add_account_does_not_promote_to_active` (FR-045 / B-E2E-N1 manager-layer lock the packet REQUIRES). |
| test_settings_headers.py (7) | settings-headers.test.ts (N1+N2) | 5/5 in-scope | `TestSessionHeadersOnOutboundRequests` (2) NOT re-translated — B0-owned, header-cited (playbook :244-246). Body diff of TestSettingsHeaderAttachment + TestNoEnvMutation vs source :52-96: assert-for-assert faithful (full env snapshot compare preserved). |
| test_auth_storage.py (48) | auth-storage.test.ts (N2) | 48/48 | Header claim "no O_*-flag assert exists in TestOAuthStorageSecurityHardening" VERIFIED against source :87-196 (true — the fd-flag members live in test_storage.py). Threads→async-racers re-expression header-cited. (The lone `"test_client` grep extra is a `clientId` literal, not a test.) |
| test_storage.py (15) | storage-paths.test.ts (N2) | 13/15 | 2 Python-only, both header-cited (see F3 for the cosmetic wording). |
| test_token_resolver.py (18) | token-resolver.test.ts (N2) | 18/18 (1 rename threads→racers) | +5 extras all accounted: 4 = inbound `TestTokenResolverMalformed` (names match), 1 = ASR-F4c named re-take `test_session_to_credentials_oauth_browser_missing_tokens_raises`. |
| test_bridge_export.py (19) | bridge.test.ts (N2) | 15/19 + 4 re-expressions | +4 extras = inbound `TestBridgeEdgeCases` (all 4 names match). `TestAccountsNamespaceWiring` (4) re-expressed against `createNodeBridgeEffects` with header-cited split; active-account fall-through re-covered at `accounts-namespace.test.ts:811` (+ swap-in copy); **the settings-custom-header composition is Finding F1**. |
| test_auth_flow.py (37) | oauth-flow-refresh (N2) + oauth-flow-login (N3) | 37/37 — name diff EMPTY | Split exactly per packet §3.3/§4.3 (NetworkErrors refresh/timeout members in the refresh file, exchange members in login; header-cited both sides). Body diff of TestOAuthFlowRefresh (:490-609) vs TS: every Python assert present; STRENGTHENED with the exact insertion-order `body_text` lock, URL and content-type asserts (packet §3.2 item 1), and the pre-request refusal `captured.length === 0` (item 2). |
| test_auth_pkce.py (9) | pkce.test.ts (N3) | 9/9 | RFC 7636 rows present (+1 extra invariant case). |
| test_auth_registration.py (13) | client-registration.test.ts (N3) | 13/13 | — |
| test_auth_callback.py (12) | callback-server.test.ts (N3) | 12/12 | incl. `TestCallbackHtmlSecurity` (caution 13). Real 127.0.0.1 binds per packet §4.3. |
| test_me.py MeCache classes (12 of 44) | me-cache.test.ts (N2) | 12/12 (1 rename threads→writers) | Models/`TestMeService` NOT re-translated — header-cited to their B4-C1/B6 homes per the packet row. Ordered re-hydration suite present (:270). |
| test_workspace_init.py::TestBridgeTokenMaterialization (1) | workspace-bridge-materialization.test.ts (N2) | 1/1 + 1 resolver-chain extra | HOME DEVIATION disclosed in-header (core-purity eslint boundary covers core TEST files; relocated to packages/node with citation); the core `workspace-init.test.ts` deferral row dropped in the same commit ("ZERO deferrals remain"). |
| NEW naming-order lock | core/test/accounts/naming-order.test.ts (MAPFIX) | 9 tests | header cites user-ratifications.md:14-22 as required by packet §2.3. |
| NEW CRED-F3 round-trip | secret-roundtrip.test.ts (N1) | 2 tests | SA + OT reveal equality + on-disk plaintext + explicit no-mask assert — the §2.2 mandatory deliverable. |

No un-cited drop found in any file. Every Python-only exclusion traces to plan
§2.2 / the R9.2 fd-flag drop or a batch-home split with citation.

### E2 — UNPORTED_AUTH_SEAMS closure (grep + sweep)

- `grep -rn "UNPORTED" packages/node/src` → comments only; **zero throw sites,
  zero `unportedAuthSeam(` references** in the node package. The core defaults
  (`auth-effects.ts:477-487` constant + `unportedAuthSeam`) STAY by design
  (packet §4.4 core-alone posture).
- `auth-effects-bag.test.ts:101-231` — the §4.4 mechanical sweep — invokes
  EVERY constant name over the real bag against tmp-dir state: `config.*`
  (13 members incl. transactions), `env`+`env.get`, `tokenStore.*` (all 6 incl.
  `accountDirExists` = the B7-ARB-A SEM-F2 seam and `writeTokens`-returns-path),
  `tokenResolver` (static; browser path covered in token-resolver.test.ts),
  `bridge.*` (load/export/remove), `meCache.put`, `persistActive` (the
  `UNPORTED_RESOLVER_SEAM` residue closure), `readSecretStdin`, `narrate`,
  plus `resolverSeamsFromEffects` routing and a closing assert that the
  committed constant equals the owner map. `oauthFlow.login` exercised by the
  dedicated real-flow test (:235). `readFile` (W7-D1) = `fs-seams.ts`
  `nodeReadFile`; the core default's UNPORTED_FILE_READ_SEAM test at
  `governance-data.test.ts:1239` correctly still asserts the core-alone throw.
- All 20 node test files + naming-order: **357/357 green** (self-run).

### E3 — MAPFIX verification (all four required checks)

1. **Red repro (self-run)**: `git worktree add` at pre-fix `9fb09ef`, copied
   `naming-order.test.ts` in, `npx vitest run` → **8 failed / 1 passed** —
   byte-matches the recorded red run (B8-MAPFIX-notes.md). The failures are
   BEHAVIORAL (first-listed-org pick, collision-suffix base, resolveWorkspace
   tie-break), i.e. the genuine Python-vs-JS integer-key-hoisting divergence,
   not mere type-shape asserts; the single pass is the order-insensitive
   toJSON content check. Worktree removed after.
2. **Exclusion removed**: `naming.ts:105-118` JSDoc now cites the ratification
   and states "The former ascending-id fuzz-domain exclusion is REMOVED"; the
   fuzz (`throwaway/b8-mapfix/org-order-fuzz.ts`) draws SHUFFLED key orders
   (integer-like + non-integer mixes) per its domain comment.
3. **Out-of-order strategies present + reproduced**: re-ran
   `org-order-fuzz.ts` → `examples 1000 divergences 0 seed 20260816`
   (matches RUN record). CPython-differential arm recorded at 1,000 cases /
   0 divergences (naming 600, workspace 400 @ fd91a81).
4. **N2 follow-through on the MAPFIX note-3 flag**: `me-cache.ts:23-28` +
   `stringifyOrdered` (:315-…) — the me.json WRITER serializes the three
   container maps in insertion order (option (a), no disclosed narrowing
   needed); read side re-hydrates via `parseLossless` → `toNativeJson` →
   `fromDict`; locked by `me-cache.test.ts:270` ("Ordered-organizations
   re-hydration") and `throwaway/b8-n2/fs-probes.ts:638`.

### E4 — 7-vector replay (self-run)

`npm run conformance` at HEAD: **3,251 total — 3,251 passed / 0 failed /
0 skipped_unported (corpus @ 70c904dc598d)** = the B7 baseline 3,244 + the 7
`oauth_flow.refresh_tokens` vectors passing bound-while-pending.
`batch-status.ts:119` still `["oauth_flow.", "pending"]`, last touched at the
B7 gate commit — **no premature flip** (packet §3.4 rule honored; the flip is
the gate task's).

### E5 — core-purity boundary

- `grep` over `packages/core/src`: **zero** `from "node:*"` /
  `require("node:*")` imports (the MAPFIX core touches — `json-value.ts`,
  `lossless-json.ts`, `model-base.ts`, `me.ts`, `naming.ts` — and the N2
  `token.ts` touch are all pure).
- `npx eslint packages/core/src packages/core/test` → exit 0, no output.
- The one test that NEEDED node:fs (`TestBridgeTokenMaterialization`) was
  relocated to `packages/node/test` with a disclosed citation rather than
  weakening the boundary (E1 row).

### E6 — GATE-R5 lossless grep (flow.ts / client-registration.ts / me-cache.ts)

Wire response bodies parse via `parseLossless` only (`flow.ts:827,872`,
`client-registration.ts:187`); `me-cache.ts:170` reads through
`parseLossless` too (required by the ordered path). The remaining
`JSON.parse` sites (`token-store.ts:64`, `token-resolver.ts:201`,
`bridge.ts:231,291`, `storage.ts:340`) are ON-DISK FILE reads whose Python
twins are `json.loads` — noted for the arbiter: `json.loads` accepts
`NaN/Infinity` where `JSON.parse` throws, but on every such path both sides
terminate in the same coded corrupt/invalid branch (or null-return for
MeCache), so the class is equivalent; not a finding (semantics-lens FYI).

### E7 — harness RUN spot-checks (P3-2(d) item 5)

Re-run from recorded seeds, all byte-matching their RUN records:
- `throwaway/b8-n1/config-model-fuzz.ts` → `runs 500 ops 2994
  error-agreements 2220 divergences 0 seed 20260816` ✓
- `throwaway/b8-mapfix/org-order-fuzz.ts` → `examples 1000 divergences 0
  seed 20260816` ✓
- `throwaway/b8-n2/fuzz.ts` → 5 surfaces (refresh classifier, storage path
  layout, bridge resolution order, MeCache TTL, quote_plus agreement) all
  `seed=20260816 runs=500 zero-divergence` ✓
- `throwaway/b8-n3/fuzz.ts` → 4 surfaces (pkce-vs-minimodel,
  parseqs-roundtrip, paste-parser, authorize-url-roundtrip) all
  `seed=20260816 runs=500 zero-divergence` ✓

### E8 — misc lens duties

- Real-home guard: `packages/node/test/helpers.ts:29-40` refuses any resolved
  path under `os.homedir()` (caution 3 / Python conftest discipline mirrored).
- Repo-wide `B8` grep over test headers: only historical citations remain
  (`resolver.test.ts:13`, `governance-data.test.ts:35,1239`,
  `headers.test.ts:5`, etc. — statements of B8 ownership now satisfied, none
  an open deferral row). See F2 for the src-side stale TODO(port) wording.
- `token.ts` `expires_at` TODO(port): REMOVED; rendering now vector-locked
  (`+00:00`, seconds precision) — all 7 vectors pass (E4).

## Per-shard coverage record (orchestrator ruling)

- **MAPFIX** — E3 in full (red repro self-run, mechanism, exclusion removal,
  fuzz re-run, N2 flag follow-through).
- **N1** — io-utils/config/settings-headers/secret-roundtrip dispositions +
  bodies (E1), config fuzz re-run (E7), FR-045 promotion lock present,
  bag `config.*`/`env`/`readSecretStdin` closure (E2).
- **N2** — auth-storage/storage-paths/token-resolver/bridge/refresh/me-cache/
  materialization dispositions + refresh-class body diff (E1), vectors (E4),
  N2 fuzz re-run (E7), F1 raised here.
- **N3** — pkce/registration/callback/login dispositions (E1), §4.4 sweep
  (E2), N3 fuzz re-run (E7).
