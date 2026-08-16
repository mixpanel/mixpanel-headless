# B7-A1 — accounts/session/targets namespaces + naming + ResolverSeams (shard notes)

**Status**: DONE (module task, P3-2 a+b+c; no vectors — Layer-3 is the
lock, packet §0 Risk-7 posture). Packet:
`context/phase3/design/b7-packets.md` §3. Model: fable, ≤ high.
Depends on B7-A2 (verified on disk before starting: `resolver.ts`,
`region-probe.ts`, `wire-auth.ts`, `throwaway/b7-a2/`, `B7-A2-notes.md`).
TS commit: see `mixpanel-headless-ts` main (B7-A1 shard commit).

## What landed (TS repo)

| file | role |
|---|---|
| `packages/core/src/accounts/naming.ts` | `slugify` + `defaultAccountName` (`naming.py` whole file) |
| `packages/core/src/accounts/auth-effects.ts` | `AuthEffects` seam bag (packet §3.2) + `ConfigWrites` + `defaultAuthEffects()` (every B8-owned member throws `UNPORTED_AUTH_SEAM` with `{seam}`) + the committed `UNPORTED_AUTH_SEAMS` constant |
| `packages/core/src/accounts/accounts-ops.ts` | `accounts.py:64-1029` — module helpers (`_FreshBrowserBearer` twin, `_fetch_me`, `_domain_to_region`, E-2 cross-check, test-failure builder) + list/add/derive/update/remove/use/show/test/login/logout/token/export_bridge/remove_bridge |
| `packages/core/src/accounts/login-unified.ts` | `accounts.py:1030-2013` — detection, flag validation, relogin state machine, browser/credential new flows, `_resolve_project` chain, `_summary_with_me` (split file per the packet's ~800-line R7 rule) |
| `packages/core/src/accounts/{namespace,session-namespace,targets-namespace}.ts` | `createAccountsNamespace` / `createSessionNamespace` / `createTargetsNamespace` factories over the bag (B8 exports the ready-made objects) |
| `packages/core/src/accounts/resolver-seams.ts` | `resolverSourcesFromEffects` + `resolverSeamsFromEffects` (4 of 5 W1-D1 seams REAL; `persistActive` ROUTED to the still-stubbed effect) + `persistActiveToConfig` (the `workspace.py:695-722` applySession routing B8 binds to disk) |
| `packages/core/src/workspace.ts` | B7 resolver CONSTRUCTOR: `WorkspaceOptions` gains `account/project/workspace/target` + injected `sources`; WS1 guard fires first (`workspace.py:455-465`); the B5 "resolved-Session-only" TODO removed; per-account me-cache STORE memo (see disclosure 6) |
| `packages/core/src/index.ts` | `accounts/` barrel exported (closes the four deferred `__all__` names at the factory level; ready-made objects are B8) |
| `throwaway/b7-a1/{namespace-branches,ops-fuzz}.ts` + `RUN.md` | R10.9 harness (§3.6) |

## Layer-3 (§3.4 — every row placed)

| TS file | tests | source |
|---|---|---|
| `test/accounts/naming.test.ts` (22) + `naming.pbt.test.ts` (8) | TestSlugify + TestDefaultAccountName + 8 properties, same strategy shapes | `test_naming.py`, `test_naming_pbt.py` |
| `test/accounts/accounts-namespace.test.ts` (44) | ALL non-login_unified classes; `TestSummaryTableDynamicWidth` EXCLUDED (CLI formatter, plan D4 — header-cited); `TestPublicSurface` folded to one namespace-surface assert (no runtime `__all__`) | `test_accounts_namespace.py:46-991` |
| `test/accounts/login-unified.test.ts` (16) | the six `TestLoginUnified*` classes (activation, me-cache write, flag matrix, summary fields, progress hook incl. the enter→fetch→exit ordering spy, picker sort order) | `:993-1685` |
| `test/accounts/session-namespace.test.ts` (6) / `targets-namespace.test.ts` (15) | whole files | `test_session_namespace.py`, `test_targets_namespace.py` |
| `test/accounts/login-region-check.test.ts` (4) | E-2 wording + atomic-publish (no tokens after failure) | `test_login_region_check.py` |
| `test/accounts/secret-redaction.test.ts` (4) | `TestSecretLeakage` whole class; `TestCliExitCodes` EXCLUDED per plan D4 (decision recorded in packet §3.4 + here) | `test_042_edge_cases.py:615-681` |
| `test/workspace/workspace-use.test.ts` (+14 → 37) | de-deferred `TestUseAccount`/`TestPersist`/`TestUseAccountEnvVarPriority`/`TestUseTargetEnvOverride`/`TestUseAccountWorkspaceEnvValidation` + the 4 seam-bound W1-class cases — REAL `resolverSeamsFromEffects`; header now lists ZERO B7 deferrals | `test_workspace_use.py` |
| `test/workspace/workspace-init.test.ts` (+9 → 16) | `TestActiveResolution`/`TestExplicitOverrides`/`TestTarget` via the resolver constructor + the :969/:975/:1021 constructor-guard trio + the FULL use-chain-equivalence twin; only `TestBridgeTokenMaterialization` (→ B8) remains deferred | `test_workspace_init.py`, `test_workspace.py:969-1030` |
| `test/workspace/workspace-facade.test.ts` (+4 → 35) | `TestFacadeResolverWiring` (4 tests incl. account-swap cold-cache fall-through + injected-resolver preservation); `TestCredentialResolution` recorded as EMPTY in Python (B1 Fix 10) — nothing to port | `test_workspace_resolution.py:611-791`, `test_workspace.py:96` |
| `test/workspace/workspace-oauth.test.ts` (5, new) | all three classes (session-bypass + injected client) | `test_workspace_oauth.py` |
| `test/services/me-service.test.ts` (+2 → 29) | `TestMeServiceResolveWorkspace` — 2 non-duplicate cases translated; 3 literal duplicates cited to the existing dagger-path section (header note) | `test_workspace_resolution.py:154-213` |
| `test/client/client-workspace.test.ts` | header only: the stale "is B8"/"is B6" rows corrected (packet Caution #17) | — |
| `test/accounts/fake-auth-effects.ts` | shared in-memory `AuthEffects` bundle (config fake implements the ConfigManager transaction semantics the `ConfigWrites` JSDoc pins; `meFetch` wraps payloads in the app-API `results` envelope) | infra |

## Checkpoint numbers (2026-08-16)

- `npm run check`: green (typecheck ×5, eslint incl. the R9.1 purity
  boundary — no `node:*` / `process.env` in core — prettier, **9,368**
  vitest tests / 211 files, browser-bundle smoke).
- `npm run conformance`: **3,251 — 3,244 PASS / 0 FAIL / 7 UNPORTED**
  (unchanged from A2; A1 owns 0 vectors).

## R10.9 RUN record (mirror of `throwaway/b7-a1/RUN.md`)

```
npx vite-node throwaway/b7-a1/namespace-branches.ts
npx vite-node throwaway/b7-a1/ops-fuzz.ts

namespace-branches: checks 352  failures 0  captured-errors 72
ops-fuzz: sequences 600 (>=500 budget)  ops 3676  divergences 0  seed 20260818
```

Row groups: §3.6 item 1 (~90 error-branch rows incl. the flag matrix,
E-2/E-3/E-4/E-6/E-8, force-remove orphans, WS1 guards), all 35
`UNPORTED_AUTH_SEAM` defaults by name + the ONE remaining unported
real-seam path (`persist: true` with B8 absent), item-2 sweep (detect ×3
× region explicit/probed × project explicit/picked/single/none = 24
runs + 3 relogin arms), item-3 edge set, item-4 sentinel sweep (72
captured errors × message + `toDict()` JSON, sentinel-free). ops-fuzz:
independent mini-model, zero divergences.

## Decisions / disclosures (review-pair + arbiter input)

1. **Caution #13 — `default_account_name` first-org pick (NOT
   self-sanctioned; ESCALATED to the shard arbiter)**: Python picks
   dict INSERTION order; TS `MeResponse.organizations` is a plain
   Record whose integer-like org-id keys JS hoists ascending.
   Divergence whenever `/me` emits orgs out of ascending-id order (no
   recorded fixture does). Implementation uses `Object.entries` order;
   disclosed in `naming.ts` JSDoc; arbiter to rule per the packet's
   #9/#10 options (unreachable-note / fuzz-domain exclusion / ordered
   container).
2. **Browser new-account flow mechanism substitution**: Python's
   `.tmp-{nonce}` placeholder-dir + `os.rename` atomic publish
   (`accounts.py:1616-1750`) becomes validate-in-memory THEN
   `tokenStore.writeTokens` + rollback via `removeAccountDir` on add()
   failure. Observable contract identical (E-2 failure leaves no
   tokens — locked in `login-region-check.test.ts`; post-persist add
   failure rolls the dir back — harness); write-atomicity itself is
   B8's `writeTokens`. Header-cited in `login-unified.ts`.
3. **Packet-gap AuthEffects additions (disclosed)**: `readSecretStdin`
   (stdin is a node effect the §3.2 table missed; UNPORTED default,
   added to `UNPORTED_AUTH_SEAMS`; owner B8) and `narrate` (stderr
   write; default NO-OP since the messages are out of contract R5.4 —
   NOT in the unported list; B8 wires `process.stderr`). `tokenStore`
   shape adjusted from the packet's indicative members:
   `clientInfoExists(region)` → `clientInfoPath(region)` (needed for
   `OAuthLoginResult.client_path`), `writeTokens` returns the written
   path (`tokens_path`), `removeTokens` added (`logout`).
4. **`persistActive` stays the ONE stubbed W1-D1 seam** (packet §3.2):
   `resolverSeamsFromEffects` routes it to `effects.persistActive`
   (default throws `UNPORTED_AUTH_SEAM`); the actual
   `_persist_active` composition (`applySession` +
   `clear_workspace`) ships as `persistActiveToConfig` for B8 to bind
   and for tests to wire to the fake config.
5. **`accounts.test()` non-library arm**: Python wraps
   `httpx.HTTPError` into coded `HTTP_ERROR` (`api_client.py:801-804`)
   — so does the TS transport; the Python test's raw-`OSError` leak
   re-expresses as a plain `Error` at the token-resolver seam (the
   only sub-transport leak site). Header-cited in
   `accounts-namespace.test.ts`.
6. **Per-account me-cache STORE memo in `Workspace`** (src change):
   Python's `MeCache(account_name)` re-reads the same per-account disk
   file across `MeService` rebuilds, so `use(project=…)` keeps the
   warm cache (`TestFacadeResolverWiring::test_resolver_follows_
   project_swap`). The default `inMemoryMeCache` factory produced a
   COLD store per rebuild — the facade now memoizes one store per
   account name (JSDoc-cited). B8's on-disk factory is unaffected.
7. **Naming decision (§3.5 / B6 Caution-6, recorded)**: namespace
   METHOD names are camelCase like the facade (`exportBridge`,
   `removeBridge`, `loginUnified`); options-bag KEYS keep Python kwarg
   spelling (`default_project`, `token_env`, `derive_name`,
   `no_browser`, `secret_stdin`, `open_browser`, `account_type`,
   `project_picker`, `progress`).
8. **ProgressFactory mapping** (packet §3.3): the Python context
   manager becomes `(msg) => ({end()})` — enter = the factory call,
   exit = `end()` in a `finally`; the enter→fetch→exit ordering is
   locked by the translated progress-hook tests via a fetch-level spy.
9. **Python `TypeError` twins** (`derive_name` conflicts) port as
   `ParamTypeError` (the Phase-2 TypeError-dual class, R5.5 generic
   code); the `session.use` / resolver / constructor target guards all
   reuse `WS1_TARGET_MUTUALLY_EXCLUSIVE` (packet Caution #14 — no new
   codes minted).
10. **Edge-set correction, CPython-verified** (2026-08-16, uv run):
    `slugify("𝒳")` is `"x"` — U+1D4B3 is a COMPATIBILITY character
    NFKD folds to "X" (the packet's fuzz-domain note stands for
    NON-compat astral chars like "🎉" → ""). Harness rows updated;
    also `slugify("18.0") == "18-0"` pinned both sides.
11. **`Workspace` construction without `session` or `sources`** throws
    `UNPORTED_AUTH_SEAM` `{seam: "workspaceSources"}` — B8's node
    wiring supplies the on-disk defaults so bare `new Workspace({})`
    matches Python `Workspace()`. `TODO(port)` at the site.
12. **Formatting fix to `throwaway/b7-a2/RUN.md`** (table alignment
    only): the committed A2 file failed the CURRENT `prettier --check`;
    reformatted in the A1 commit so `npm run check` stays green. No
    content change.

## Pair-A arbiter follow-up (2026-08-16, `b7-reviewA-resolution.md`, TS commit `4c8946a`)

- Disclosure 1 (Caution #13) **RULED** (resolution ruling R2): standing
  disclosed divergence per the Discrepancy #9/#10 mechanism; naming fuzz
  domain stays ascending-id (documented omission); the ruling extends to
  the two sibling out-of-contract sites (the "Accessible projects:"
  error-listing order and picker tie order). `naming.ts` JSDoc cites the
  ruling; the gate pastes the proposed playbook discrepancy entry #13.
- Disclosure 2 **EXTENDED + branch RESTORED** (SEM-F2): the Python
  orphan-directory guard (`accounts.py:1704-1708`) had NO TS equivalent
  (silent `writeTokens` overwrite). Fixed red-first via a NEW
  `TokenStore.accountDirExists(name)` seam (B8-N2 implements as
  `account_dir(name).exists()`; the fake reports held state). Residual
  disclosures: the TS message renders the NAME where Python renders the
  directory PATH (R5.4, class+code identical), and in the overlap state
  (config record AND dir both exist) TS raises `AccountExistsError`
  where Python raises the dir-exists ConfigError — both refuse.
- **SEM-F1 falsiness fixes** (red-first, 5 spec-cited tests): three
  Python falsy-`or` param sites had been ported as nullish-`??` —
  `test("")` → `"(none)"` (`accounts.py:727`), `export_bridge(account="")`
  → active-account fall-through (`:997`), `login_unified(token_env="")`
  → `MP_OAUTH_TOKEN` fallback then the probe's empty-pointer ConfigError
  (`:1812`; CPython-verified end-to-end). Arbiter `' or '` sweep found
  no further sites (`default_project` twins are model-locked `^\d+$`,
  `??` equivalent).
- Disclosure 3 tokenStore shape gains `accountDirExists` (covered by the
  `UNPORTED_AUTH_SEAMS` `"tokenStore.*"` group entry; B8-N2 owner).
- `TestSummaryTableDynamicWidth` exclusion **RATIFIED by the arbiter**
  (ASR-F1) — now an arbiter decision, not an implementer deviation.

## Pair-B arbiter follow-up (2026-08-16, `b7-reviewB-resolution.md`)

- **Reveal-site enumeration (CRED-F1 remediation — the packet §3.3
  "enumerate each reveal call in the shard notes" duty, previously
  satisfied only by the `accounts-ops.ts` module header)**. The
  complete `reveal()` allowlist after B7, arbiter-re-verified by grep
  against both repos, exactly 1:1 with Python's `get_secret_value()`
  sites:

  | TS `reveal()` site | Python twin | Purpose |
  |---|---|---|
  | `auth/account.ts:585` (`accountAuthHeader`, Phase-2) | SA header build (accountAuthHeader twin) | Basic header |
  | `auth/region-probe.ts:382` | `region_probe.py:246` | SA Basic probe header |
  | `auth/region-probe.ts:387` | `region_probe.py:250` | inline oauth_token Bearer |
  | `accounts/accounts-ops.ts:726` | `accounts.py:844` | `login` → `freshBrowserBearer` (in-memory pre-persist probe) |
  | `accounts/login-unified.ts:593` | `accounts.py:1665` | `_login_unified_new_browser` → `freshBrowserBearer` |

  No extra reveal introduced, none dropped. Distinct-but-allowed
  plaintext surfaces (NOT `reveal()` sites): `accounts.token()` returns
  the plaintext bearer (Python's documented public behavior,
  `accounts.py:931-962`); test-side `reveal()` calls in
  `fake-auth-effects.ts` are the designated store writes (ConfigManager
  persists plaintext in `config.toml` on the Python side too).
- **Disclosure 13 (CRED-F2, cosmetic, SAFE direction)**: TS `Secret`
  renders `'**********'` for an EMPTY wrapped value where Pydantic
  `SecretStr('')` renders `''` (arbiter re-verified against live
  CPython: `str`/JSON both `''`). Phase-2-owned `secret.ts`, unchanged
  in B7 but newly load-bearing here; the only B7 `new Secret("")` site
  (`login-unified.ts:763`) is a defensive unreachable fallback in the
  SA arm. MORE redaction, never less — no code change; carry into
  `B7-notes.md` at the gate. Re-examine only if a serialized bag is
  ever byte-diffed against Python output containing an empty SecretStr.
- **B-E2E-F1 fix (duplicate `accounts.add` error class)**: the
  `ConfigWrites.addAccount` JSDoc + `fake-auth-effects.ts` throw site
  claimed/raised `AccountExistsError` (ACCOUNT_EXISTS) where Python's
  `ConfigManager._apply_add_account` raises PLAIN `ConfigError`
  (`config.py:446`; `AccountExistsError` is the login_unified
  name-collision path only, `accounts.py:1689`). Fixed red-first
  (new lock in `accounts-namespace.test.ts`: duplicate add →
  CONFIG_ERROR, constructor === ConfigError, message byte-equal).
- **B-E2E-N1 (promotion layering, docs)**: `ConfigWrites` JSDoc now
  attributes the FR-045 first-account promotion to the `accounts.add`
  NAMESPACE transaction (`accounts.py:472-489`), not to
  `ConfigManager.add_account` (which does not promote); B8-N1
  implements it exactly once in the adapter transaction and keeps the
  ConfigManager twin non-promoting (`test_config.py` asserts are that
  layer's lock).
- **CRED-F3 (outbound B8 rule, docs)**: `auth-effects.ts` module header
  now carries the SECRET SERIALIZATION RULE — on-disk credential
  writers must `reveal()` at the designated write site, never route a
  `Secret` through `JSON.stringify` (which would persist the literal
  mask); B8 adds a write→read round-trip Layer-3 lock.

## Deferral notes for B8 / the gate

- B8 implements BY NAME: everything in `UNPORTED_AUTH_SEAMS`
  (`accounts/auth-effects.ts`) — `config.*` (TOML ConfigManager
  honoring the `ConfigWrites` transaction contracts), `env`
  (process.env), `tokenStore.*` (per-account 0o600 storage incl. the
  placeholder-dir atomicity), on-disk `tokenResolver`,
  `oauthFlow.login` (PKCE), `bridge.*`, on-disk `meCache`,
  `persistActive` (bind `persistActiveToConfig`), `readSecretStdin` —
  plus the ready-made `accounts`/`session`/`targets` exports and the
  `ResolverSources` default wiring for bare `Workspace()` construction.
- `test_workspace_init.py::TestBridgeTokenMaterialization` (:167) stays
  B8 (header row kept in `workspace-init.test.ts`).
- Gate (§4): no A1 flip duty (0 vectors); delete `throwaway/b7-a1/`
  after arbiter sign-off; Caution #13 arbiter ruling follow-through.

## Progress checklist (final)

- [x] Layer-3 tests translated (§3.4) — 10 files touched/created, all green
- [x] `packages/core/src/accounts/naming.ts`
- [x] `packages/core/src/accounts/auth-effects.ts` (+ `UNPORTED_AUTH_SEAMS`)
- [x] `packages/core/src/accounts/accounts-ops.ts` + `namespace.ts`
- [x] `packages/core/src/accounts/login-unified.ts`
- [x] `packages/core/src/accounts/session-namespace.ts` / `targets-namespace.ts`
- [x] `packages/core/src/accounts/resolver-seams.ts` (4 of 5 seams REAL)
- [x] Workspace constructor resolution (axes + `sources=`) + WS1 twin
- [x] De-deferred B6 classes green; headers zeroed of B7 rows
- [x] R10.9 harness `throwaway/b7-a1/` + RUN record (§3.6)
- [x] `npm run check` green (9,368 tests); conformance unchanged 3,244/0/7
- [x] Local commits (TS + this notes file)
