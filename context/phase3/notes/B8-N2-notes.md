# B8-N2 notes — storage + refresh flow + OnDiskTokenResolver + bridge + MeCache (b8-packets.md §3)

Status: shard COMPLETE · 2026-08-16 · agent: B8-N2 (fable).
Spec: `context/phase3/design/b8-packets.md` §3 (+ §0.2 mapping, §0.3.2 core touch, §7 cautions).
TS commit: see `packages/node` shard commit on `main` (this shard); Python repo carries ONLY these notes.

## 1. What landed

**Sources** (`packages/node/src/`):
- `auth/oauth-constants.ts` — `OAUTH_BASE_URLS` (home moved from `client_registration.py:39-44` per §3.1 row 2; N3 imports from here).
- `auth/storage.ts` — `storageRoot`/`accountsRoot`/`accountDir`/`ensureAccountDir` (`storage.py:53-142`) + `OAuthStorage` (`storage.py:193-635`) with the lstat-substituted `checkAndFixPermissions` (module-header cites the sanctioned R9.2 fd-hardening drop; TOCTOU residue → Phase-4 row).
- `auth/token-payload.ts` — `tokenPayloadBytes` (`token.py:188-212`; designated CRED-F3 reveal site).
- `auth/flow.ts` — `OAuthFlow` REFRESH HALF (`flow.py:118-179`, `:180-226`, `:442-605`): ctor + region validation, `getValidToken`, `refreshTokens`, `#postTokenRequest` with the vector-locked classifier. Transport via core `createRequestExecutor` (R2.10); body parse via `parseLossless` + `isPlainRecord` (GATE-R5; watchlist #13 canonical guard). N3 extends this file with the login half.
- `auth/token-resolver.ts` — `OnDiskTokenResolver` (`token_resolver.py:1-288`) incl. rotation-keep (`:236-241`), symlink-before-existence probe, per-account atomic rewrite; injectable seams `loadClientInfo`/`refresh`/`now`/`env` are the `monkeypatch.setattr` twins the Python tests use.
- `auth/bridge.ts` — `BridgeFile` v2 parse (`extra="forbid"`, `Literal[2]`, `^\d+$` project regex, PositiveInt workspace), `loadBridge`/`exportBridge`/`removeBridge` (`bridge.py:1-409`), `bridgeViewFromFile`, `materializeBridgeTokens` + `loadBridgeForStartup` (the `workspace.py:476-513` ctor side effect, incl. the empty-scope→`"read"` default), `createNodeBridgeEffects`.
- `auth/token-store.ts` — real `TokenStore` (auth-effects.ts:305-362) incl. `accountDirExists` (B7-ARB-A SEM-F2), `writeTokens`-returns-path, `clientInfoPath(region)`, `removeAccountDir` warn-never-raise.
- `me-cache.ts` — on-disk `MeCache` (`me.py:413-607`) implementing core `MeCacheStore`, + `createNodeMeCacheEffects` (`_persist_me_cache`, `accounts.py:1338-1356` — passes `storageDir=accountDir(name)` so the override is honored; the DEFAULT MeCache dir reads `Path.home()/.mp` directly, verbatim Python, `me.py:459`). PII chmod-failure RAISES ConfigError (caution 12).

**Core touch (§0.3.2, sanctioned)**: `packages/core/src/auth/token.ts` — `pythonUtcIsoformat` (isoformat rendering: `+00:00`, 0-or-6 fractional digits), `fromTokenResponse(data, {now})` + `isExpired({now})` optional clock seams (existing callers unchanged). The Phase-2 `expires_at` rendering TODO marker is REMOVED (closed, not re-scoped; zero `TODO(port)` markers remain in `packages/node` + `token.ts`).

**Binding (§3.4)**: `conformance-runner/src/wire-auth.ts` registers `oauth_flow.refresh_tokens` over the REAL node `OAuthFlow` (node context; region `us`, frozen `context.shims.now()` clock, tmp-dir storage stub never consulted). Binding honesty: kwarg plumbing + the recorder `_encode_common` output walk only. NO batch-status flip (bound-while-pending; flip is the gate's).

**Replay**: `npm run conformance` → **3,251 passed / 0 failed / 0 unported** (corpus @ 70c904dc). The 7 `oauth_flow.refresh_tokens` vectors pass while `oauth_flow.` is still `pending` (the designed pattern; report shows them as passes, i.e. "3,244 + 7 passing-while-pending"). `npm run check` fully green (typecheck, lint, fmt, 9,694 tests, browser smoke).

## 2. Layer-3 translation map (§3.3) — all rows placed

| Python | TS home | Notes |
|---|---|---|
| `test_auth_storage.py` (12 classes, 48 tests) | `packages/node/test/auth-storage.test.ts` | all classes translated; thread concurrency → concurrent async writers over the pid+counter tmp scheme (per-file disposition) |
| `test_storage.py` (5 classes, 15 tests) | `packages/node/test/storage-paths.test.ts` | PYTHON-ONLY (header-cited): `test_check_and_fix_permissions_uses_fchmod_not_chmod` (fd-flag mechanism probe — the drop), `test_windows_skip_does_not_crash` (`delattr(os,"O_NOFOLLOW")` shim has no node analog) |
| `test_token_resolver.py` (6 classes, 18 tests) | `packages/node/test/token-resolver.test.ts` | `monkeypatch.setattr` fixtures → ctor seams; two-thread barrier race → two concurrent async callers over a shared gate |
| `test_bridge_export.py` (4 classes, 19 tests) | `packages/node/test/bridge.test.ts` | `TestAccountsNamespaceWiring` translated against `createNodeBridgeEffects()` DIRECTLY (header-cited split per §3.3 row 4; N3's bag swap-in re-covers the namespaces) |
| `test_auth_flow.py` refresh classes (`TestOAuthFlowRefresh` :490, `TestOAuthFlowGetValidToken` :610, `TestOAuthFlowNetworkErrors` refresh member :945, `TestOAuthFlowRegionValidation` :984) | `packages/node/test/oauth-flow-refresh.test.ts` | exchange-op members of `TestOAuthFlowNetworkErrors` → N3 (header-cited split) |
| `test_me.py` MeCache classes (:228, :331, :685) | `packages/node/test/me-cache.test.ts` | `time.sleep(1.1)` TTL → injected `now`; `os.chmod` monkeypatch → injected `chmodSync`; + an ADDED ordered-orgs round-trip lock (§3.2 item 10) |
| `test_settings_headers.py::TestBridgeHeaderAttachment` :97 | `packages/node/test/settings-headers.test.ts` (extended) | bridge headers reach `Session.headers` via `BridgeView` over the real loader |
| `test_workspace_init.py::TestBridgeTokenMaterialization` :167 | `packages/node/test/workspace-bridge-materialization.test.ts` | **DISCLOSED RELOCATION** — packet said extend `packages/core/test/workspace/workspace-init.test.ts`, but the eslint core-purity boundary (`eslint.config.js:47-75`) covers core TEST files too (no `node:*`/`process` there). The core header's B8 deferral row is DROPPED and now cites the new home (zero open deferrals). The test drives `loadBridgeForStartup()` exactly as N3's default wiring will, then materializes the bearer through the REAL `OnDiskTokenResolver`. |
| `test_042_edge_cases.py::TestTokenResolverMalformed` :240 | `token-resolver.test.ts` (cited section) | inbound `b6-packets.md:1032` |
| `test_042_edge_cases.py::TestBridgeEdgeCases` :394 | `bridge.test.ts` (cited section) | + an ADDED extra-key `extra="forbid"` lock |
| `test_042_edge_cases.py:655` ASR-F4c named RE-TAKE | `token-resolver.test.ts` (cited section) | real `OnDiskTokenResolver`, isolated HOME, no injected fake; + an anti-vacuity companion row |
| (no Python file) `TokenStore` locks | `packages/node/test/token-store.test.ts` | per-member Python cites in the header (`accounts.py:278-303`, `:878-915`, `:916-929`, `:1704-1708`) |

Test-count reconciliation: auth_storage 48/48, storage 15 (13 translated + 2 Python-only, header-cited), token_resolver 18/18 (+4 edge/retake), bridge_export 19 (15 translated verbatim + 4 namespace-split re-expressions), auth_flow refresh subset 15/15, me subset 12 of 44 (the 3 MeCache classes + 1 added lock), settings_headers +2.

## 3. Vector notes

- The 7 ids (§3.4 list) replay green from the corpus bundle; the frozen clock (`2026-01-15T12:00:00Z` + `expires_in: 3600`) renders `"2026-01-15T13:00:00+00:00"` byte-exact via `pythonUtcIsoformat`.
- Error vectors: details subset-satisfied structurally — revoked ALWAYS carries `account_name` (null when unnamed), generic carries it only when supplied, transport carries `{url}` (three shapes, caution 5).
- Result vectors: the binding returns `{access_token: Secret, refresh_token: Secret|null, expires_at: PyDatetime, scope, token_type}` — the runner's `encodeExpectValue` produces the recorded shape (`$type: SecretStr` revealed / `$type: datetime`).

## 4. UNPORTED-probe exemplar swap (EARLY, disclosed — gate §5.3 finishes)

Binding the LAST pending corpus name broke three exemplar tests that used `oauth_flow.refresh_tokens` as the mapped-but-unbound probe:
- `conformance-runner/test/runner.test.ts` ("returns UNPORTED..." + the setup-gating twin),
- `differential/test/oracle-protocol.test.ts` (two UNPORTED-scope rows).

All four re-anchored to the NON-CORPUS module-known name `oauth_flow.build_authorize_url` (the `batch-status.test.ts:86` precedent — the seam takes arbitrary names; `resolveApi` classifies it `unported`, batch prefix still `pending`). This is the packet-anticipated first step of the `b6-packets.md:1033` retirement; the gate's §5.3 (a)-(c) synthetic-table re-anchor + terminal asserts land WITH the flip commit as spec'd.

## 5. CRED-F3 reveal-site enumeration (§3.6 row 7 allowlist)

On-disk plaintext appears ONLY at:
1. `packages/node/src/auth/token-payload.ts` — `tokenPayloadBytes` (`tokens.json`, both worlds: per-account rewrite + TokenStore.writeTokens + bridge materialization).
2. `packages/node/src/auth/storage.ts` `saveTokens` — legacy v2 `tokens_{region}.json` (`storage.py:469-476` twin).
3. `packages/node/src/auth/bridge.ts` `serializeBridge` — bridge file (B3 trust-boundary by design; `bridge.py:278-311` twin).
4. (N1) `config-writes.ts` `_account_to_block` twin — TOML secrets.
`me.json` carries no Secret-typed material. `OAuthClientInfo` is not Secret-bearing. Harness asserts: sentinel in NO error message/details; no `**********` mask persisted anywhere under the isolated root (fs-probes rows).

## 6. R10.9 RUN record — `throwaway/b8-n2/` (all reproduced from recorded seeds)

| Script | Coverage (§3.6 rows) | Result |
|---|---|---|
| `refresh-probes.ts` | rows 1 (branch matrix: no-refresh/transport/400+401 invalid_grant/non-invalid_grant/unparseable-400/403-404-500-503 status gate/200 non-JSON/200 missing-field matrix/rotation-null-at-flow/fractional-expires_in rejection/isoformat table), 3 (truth table incl. now = expiry−31s/−30s/−29s), 7 (refresh-half sentinel sweep) | **77 checks, 0 failures — ZERO-DIVERGENCE** |
| `fs-probes.ts` | rows 2 (0600/0700 + no-tmp-strays + reveal-no-mask on save_tokens/save_client_info/writeTokens/bridge-export/me.json; symlink+dangling read refusals; parent-symlink no-chmod-through), 4 (resolver sweep: static inline/env-set/env-empty/env-unset; browser missing/malformed/model-invalid/fresh; expired→refresh→rotation-KEEP→persisted-bytes 0600; concurrent refreshers, once-per-caller), 5 (3-type round-trips with revealed secrets; ghost-export no-partial-file; v1/v3/"2"/extra-key/naive-datetime/browser-no-tokens refusals; MP_AUTH_FILE precedence; remove env-chain/explicit/idempotent; symlinked bridge; materialize overwrite + scope default), 6 (TTL ±1 with `age > ttl` strictly-greater boundary; corrupt; chmod-failure ConfigError; ordered-orgs re-hydration), 7 (sentinel absent from resolver error surface; no-mask walk) | **53 checks, 0 failures — ZERO-DIVERGENCE** |
| `fuzz.ts` | row 8 + row-1 randomized half. Surfaces (seed **20260816**, **500 runs each**): A refresh classifier vs `flow.py:542-585` mini-model — zero-divergence; B storage path layout vs template mini-model — zero-divergence; C bridge resolution order vs `bridge.py:137-196` priority mini-model — zero-divergence; D MeCache TTL vs `age > ttl` mini-model — zero-divergence; E quote_plus agreement (REAL refresh body vs CPython urlencode mini-model: `A-Za-z0-9_.-~` literal, space→`+`, `%XX` uppercase UTF-8 — includes `*`, `~`, `+`, `&`, `=`, space, `𝒳`) — zero-divergence | **5/5 surfaces zero-divergence** |

Harness incident (recorded, harness-only): an early fuzz run flagged surface C DIVERGENT at `[false,false,true,false]` — root cause was the HARNESS restoring `process.env` by REASSIGNMENT (`process.env = {...saved}`), which severs the libuv environ binding `os.homedir()` reads, so later `HOME` writes never reached the C-level environ. Fixed with in-place restore; no library defect. (Instructive for pair-B: node `os.homedir()` reads the real environ, not the JS object, once the magic object is replaced.)

## 7. Decisions / disclosures / TODO-notes (R10.3)

1. **`loadBridgeForStartup` vs pure `load()`** — Python materializes bridge tokens ONLY in the `Workspace()` constructor (`workspace.py:476-513`); `BridgeEffects.load()` stays PURE (resolver re-reads on `use()` must not clobber tokens refreshed mid-session with a stale bridge payload). N3's default `ResolverSources` wiring must call `loadBridgeForStartup()` at facade construction and the pure loader elsewhere — recorded here as an N3 obligation.
2. **`str()` coercion corner** (`storage.py:511-517`): Python `str(data["scope"])` accepts ANY type (a dict scope would stringify); the TS twin routes `pythonStr`, which throws on non-PythonValue shapes → `loadTokens` degrades to `null` instead of stringifying exotic non-JSON types. JSON-sourced values are always in the PythonValue domain, so the divergence is unreachable from real files; noted for the reviewers.
3. **`expires_at` lax-datetime mirror**: stored string must be tz-aware AND `Date.parse`-able; numeric epoch SECONDS accepted (pydantic-lax mirror) via `pythonUtcIsoformat(value*1000)`. Garbage-with-suffix strings that CPython would reject are caught by the `Date.parse` NaN check (resolver + storage read paths).
   **[CORRECTED by B8-ARB-B, 2026-08-16 — pair-B e2e finding F1 (`b8-reviewB-resolution.md`)]**: as SHIPPED at N2 the lax mirror existed at the legacy `OAuthStorage.loadTokens` path ONLY — the OnDiskTokenResolver read (`token-resolver.ts:208`) and the `BridgeFile.tokens` parse rejected numeric epochs that Python's pydantic-lax models accept, so this decision's "resolver + storage read paths" claim did not match the code. Fixed by the pair-B arbiter: the mirror now lives in ONE shared helper (`packages/node/src/auth/pydantic-datetime.ts` `coerceLaxExpiresAt`, R10.8) routed by ALL FOUR readers (resolver, bridge tokens, `TokenStore.readTokens`, legacy storage — plus `loadClientInfo.created_at`), and was extended to full speedate fidelity (numeric-STRING epochs, the |v| > 2e10 seconds→ms watershed, the year-1..9999 range), each value live-probed against pydantic.
4. **`TokenStore.readTokens`** has no direct Python function (B7 seam abstraction; zero core call sites today). Implemented with storage-read discipline: missing → `null`, corrupt → warn + `null` (the in-memory fake precedent). Flagged for pair-A review.
5. **`_read_browser_tokens` naive-datetime parity**: Python parses `expires_at` via `datetime.fromisoformat` (naive ACCEPTED at that step) then `OAuthTokens(...)` raises pydantic `ValidationError` (NOT OAuthError) — an unhandled-escape corner. TS: the `OAuthTokens` ctor throws the coded `ParamValidationError`, which likewise propagates un-wrapped from `readBrowserTokens`. Same observable class-of-failure (validation error escapes), noted.
6. **Concurrency re-expression**: JS cannot preempt sync FS calls; Python thread races re-express as concurrent async writers/callers (per-file dispositions §3.3) — the locked contracts (no torn file, both callers served, once-per-caller IdP calls) are asserted identically.
7. **Injected logger seam (R9.5)** on `OAuthStorage`/`MeCache` (default silent, never console) is the `caplog` twin; `token-store.ts` takes the same shape for the warn-only cleanup path.
8. **`OAuthFlow` ctor kwargs**: Python's positional `region` + kwonly `storage`/`http_client` → one options bag (`region`/`storage`/`fetchImpl`/`now`); the added `now` is the §0.3.2 clock seam (D1.4).
9. **Timeout**: `DEFAULT_TIMEOUT_SECONDS = 5` (httpx client default) — not vector-observable; R2.12 unit spelling kept.
10. Two persistence worlds kept separate per caution 9 (legacy v2 region files vs per-account files); `getValidToken` persists via the legacy path only, `OnDiskTokenResolver` via the per-account path only.

## 8. Done-criteria check (§3.7)

- [x] Files on disk (§3.1 homes + `wire-auth.ts` extension + §3.3 tests)
- [x] `tsc --strict` clean (all workspaces)
- [x] Translated Layer-3 green incl. the de-deferred materialization class; `workspace-init.test.ts` header ends with ZERO deferrals
- [x] All 7 vectors PASS via `npm run conformance` (3,251/0/0 report; passing-while-pending — flip is the gate's)
- [x] `token.ts` TODO(port) marker REMOVED (closed)
- [x] Harness RUN record above (seeds + counts + zero-divergence)
- [x] CRED-F3 reveal-site enumeration (§5 above)
- [x] JSDoc complete on every new export
- [x] `npm run check` green
- [x] One local TS commit (shard) + this notes commit (Python repo)
