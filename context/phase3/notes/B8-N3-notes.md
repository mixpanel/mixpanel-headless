# B8-N3 notes — PKCE + DCR + callback server + login half + node effects-bag assembly

Status: DONE (pending doubled review). Packet: `context/phase3/design/b8-packets.md` §4.
Spec of record: phase3-playbook.md v1.1 + user-ratifications.md.

## Files landed (TS repo, `packages/node`)

| File | Content |
|---|---|
| `src/auth/pkce.ts` | `PkceChallenge` class (RFC 7636, `node:crypto` sync) + `challengeFor` (see decision 2) |
| `src/auth/query-params.ts` | `parseQs` / `pythonUnquote` — CPython `parse_qs` twin shared by callback server + paste parser (watchlist #13 single-helper discipline for query parsing) |
| `src/auth/callback-server.ts` | `CALLBACK_PORTS`, `CallbackResult`, `startCallbackServer` over `node:http` (one-shot `handle_request()` semantics; ports 19284-19287 in order) |
| `src/auth/client-registration.ts` | `ensureClientRegistered` (RFC 7591 DCR; cache-before-region-check Python order; persist-before-return) + `DEFAULT_SCOPE`; imports `OAUTH_BASE_URLS` from N2's `oauth-constants.ts` per §3.1 home note |
| `src/auth/flow.ts` (extended) | login half: `login` / `exchangeCode` / `parsePastedRedirect` (exported — Python suite drives it) / `#buildAuthorizeUrl` / `findAvailablePort`; new `OAuthFlowOptions` seams (`openBrowser`, `startCallbackServer`, `registerClient`, `findAvailablePort`, `readStdinLine`, `stderr`) |
| `src/auth-effects.ts` | `createNodeAuthEffects` (the real bag; §4.4 owner map) + `createNodeResolverSources` |
| `src/index.ts` | ready-made `accounts` / `session` / `targets` namespaces + `loginUnified` + re-exports; fresh-bag-per-call rule (see decision 6) |

Tests: `test/pkce.test.ts` (10 = 9 translated + 1 NEW RFC row), `test/callback-server.test.ts` (12),
`test/client-registration.test.ts` (13), `test/oauth-flow-login.test.ts` (22),
`test/auth-effects-bag.test.ts` (6: §4.4 sweep ×2 + TestPersist swap-in ×2 + namespace swap-in ×2).

Test-count reconciliation vs Python (packet §6 A-lens-2): pkce 9/9,
registration 13/13, callback 12/12, auth_flow login classes 22
(3 + 10 + 1 + 3 + 1 + 4 exchange-op NetworkErrors members; refresh members are
N2's `oauth-flow-refresh.test.ts`, header-cited both sides).

## Decisions / disclosures

1. **Packet/source discrepancy — PKCE verifier bytes**: packet §4.2 sketch says
   `secrets.token_urlsafe(32)`; the Python source at HEAD is
   `secrets.token_bytes(64)` (`pkce.py:65`) and the suite locks the 86-char
   verifier. Python is the arbiter → 64 bytes. (The login STATE is
   `token_urlsafe(32)` → `randomBytes(32).toString("base64url")`, `flow.py:270`.)
2. **NEW Layer-3 RFC 7636 Appendix-B vector row** (packet §4.2 mandates it;
   Python's suite has no such row): required factoring the challenge hash into
   `PkceChallenge.challengeFor(verifier)` (used by `generate()`) so the vector
   locks the CODE path, not a mini-model. Header-cited in `pkce.ts` + the test.
3. **Monkeypatch surfaces → ctor seams**: Python tests patch module attributes
   (`flow.webbrowser`, `flow.start_callback_server`,
   `flow.ensure_client_registered`); ES modules cannot be monkeypatched, so the
   login half exposes injected `OAuthFlowOptions` seams with real defaults
   (packet §4.2 names `openBrowser` explicitly; the others follow the same
   pattern). `findAvailablePort` is async in node (no sync `listen`) — the
   two-phase probe-then-bind shape is verbatim (caution 14).
4. **Losing-completer cancellation (TS-only)**: Python leaks the losing daemon
   thread (dies with the process); node's event loop would never drain with a
   live socket, so `login` aborts the loser via an `AbortSignal`
   (`StartCallbackServerOptions.signal`, TS-only member). Behavior-neutral —
   both runtimes discard the loser's outcome. Documented in the flow.ts +
   callback-server.ts headers.
5. **One-shot server mechanics**: `Connection: close` on every response +
   `closeIdleConnections()` at teardown replace Python's per-request
   `HTTPServer` teardown (graceful — no destroyed in-flight bytes). Non-GET
   requests consume the one shot and surface the Python-exact
   OAUTH_TIMEOUT-shaped no-result error (probes row1 locks it).
6. **Ready-made exports build a FRESH bag per call** (`index.ts`): the N1
   `ConfigManager` pins `MP_CONFIG_PATH` at construction (as Python's ctor
   does), so module-level namespace singletons delegate through
   `createNodeAuthEffects()` per invocation to keep call-time env semantics
   (packet §0.5 / caution 16). Python `login_unified` maps to `loginUnified`
   (standard snake→camel API naming).
7. **`parseQs`/`pythonUnquote` boundary note**: CPython `unquote(errors=
   "replace")` vs WHATWG `TextDecoder` non-fatal can differ in U+FFFD counts on
   malformed multi-byte runs — garbage-in only, no lock observes it
   (module-header documented). `URLSearchParams` NOT used (blank-value dropping
   + decode parity reasons, header-cited).
8. **Layer-3 port-stub disclosure**: `oauth-flow-login.test.ts` stubs
   `findAvailablePort` to 19284 (Python probes real ports there but never
   asserts the result) to avoid fixed-port contention with the REAL binds in
   `callback-server.test.ts` under parallel vitest workers. The REAL probe is
   locked in `callback-server.test.ts` (real binds, Python-shape) and harness
   row4 (`real probe skips 19284`).
9. **Bag sweep split**: the Layer-3 §4.4 sweep drives `oauthFlow.login`
   through injected `flowSeams` (real `OAuthFlow.login`, fake callback seam);
   the REAL-localhost-server e2e (`loginUnified` browser path, harness §4.5
   item 5) runs in `throwaway/b8-n3/probes.ts` row5 — sequential, so the fixed
   ports stay contention-free. `NodeAuthEffectsOptions.flowSeams` +
   `stdinReadSync` are test/harness seams (a real fd-0 read blocks forever on
   a quiet pipe — discovered as a hang, hence the seam).
10. **DCR `created_at`**: Python stamps ambient `datetime.now(timezone.utc)`;
    the TS port renders `pythonUtcIsoformat(now())` with `now` an optional
    seam defaulting to ambient (determinism only; not observable by any lock).
11. **`ensureClientRegistered` cache check runs BEFORE region validation**
    (Python order, `client_registration.py:91-104`): a syntactically-valid but
    unknown 2-letter region ("xx") loads null then fails the region check with
    OAUTH_REGISTRATION_ERROR; a malformed region ("US", "") propagates
    storage's `ParamValidationError` exactly like Python's bare `ValueError`.

## §4.4 seam-closure sweep (Layer-3, `auth-effects-bag.test.ts`)

Every `UNPORTED_AUTH_SEAMS` name invoked against tmp-dir state over
`createNodeAuthEffects()` — zero `UNPORTED_AUTH_SEAM` / `UNPORTED_RESOLVER_SEAM`
/ `UNPORTED_FILE_READ_SEAM` throws: `config.*` (14 members), `env` (+`get`),
`tokenStore.*` (6), `tokenResolver` (static path; browser path exercised by N2
suites + harness), `oauthFlow.login` (real flow, injected seams), `bridge.*`
(load/export/remove), `meCache.put`, `persistActive` (closes the
`lifecycle.ts` residue via `persistActiveToConfig` over the real config),
`readSecretStdin` (injected reader), `narrate` (stderr write). The constant
itself remains committed in core (core-alone posture).

## Bag swap-in runs (packet §4.3 last row — recorded)

- `TestPersist` twins (test_workspace_use.py:190) re-run over
  `resolverSeamsFromEffects(createNodeAuthEffects({configPath: tmp}))` with a
  REAL on-disk TOML: `use({account, persist: true})` lands in `[active]`;
  cleared workspace drops `[active].workspace` (fresh `ConfigManager` re-read
  asserts the disk state). 2/2 green.
- Representative namespace subset over the real bag: `accounts`
  add→FR-045-promotion→list→use; `targets` add→use→show + `session.show`
  (workspace pin lands). 2/2 green. The fake-backed core suites remain the
  primary form (not duplicated).

## RUN record (R10.9 harness, throwaway/b8-n3/)

- `npx vite-node throwaway/b8-n3/probes.ts` → **probes: 53 passed, 0 failed**
  (2026-08-16, ~1.8s). Rows:
  - Row 1 callback matrix: fallback 19284→19285; 19284+19286→19285; all-busy →
    `OAUTH_PORT_ERROR {ports:[19284,19285,19286,19287]}`; exact-port busy →
    `{port}`; two concurrent starts bind distinct ports; GET matrix — success,
    wrong state (400 + coded + expected-state NOT leaked to the browser HTML),
    `error=access_denied` (+ html.escape parity on `&<>'"`), missing code,
    wrong path (query still parsed — Python `do_GET` ignores the path),
    paramless path consumes the one shot, double-hit (first wins, second
    connection refused), non-GET → 501 + OAUTH_TIMEOUT-shaped, timeout 0.3s →
    `OAUTH_TIMEOUT {timeout_seconds}`.
  - Row 3 DCR: cached fast-path zero-fetch; redirect-uri change re-registers;
    transport → `{region, url}`; 429 with/without Retry-After (null when
    absent); non-2xx 301/400/403/500/503 → `{region, status_code,
    response_body}`; malformed 200 bodies (non-JSON / missing client_id /
    list) → coded; numeric client_id → `pythonStr` "42"; persist-before-return
    (save crash → error, next call re-registers — fetch count 2); region
    "xx" refused before any fetch; us/eu/in accepted.
  - Row 4 login state machine: browser+callback persist=false (no v2 file);
    persist=true → `tokens_us.json` exists 0o600 carrying the RAW sentinel
    (reveal site, no `**********`); no-browser banner + callback wins;
    paste wins over blocked callback; exchange 400 → generic
    OAUTH_TOKEN_ERROR (invalid_grant stays generic on exchange — caution 6);
    openBrowser throw → `OAUTH_BROWSER_ERROR {authorize_url}`; no ports →
    OAUTH_PORT_ERROR with the Python list rendering; authorize-URL param order
    locked (`response_type, client_id, redirect_uri, state, code_challenge,
    code_challenge_method`) + challenge == S256(verifier actually POSTed);
    exchange body insertion order; paste branch table (11 branches incl.
    `+`/%XX decoding); real port probe skips a squatted 19284.
  - Row 5 e2e (`loginUnified` browser path, REAL bag + REAL callback server +
    REAL port probe; injected `openBrowser` plays the browser by GETting the
    redirect URI parsed out of the authorize URL; fake register/token//me
    fetch; tmp HOME): account dir 0o700; tokens.json 0o600 + raw-token reveal
    site (no mask); me.json written; config `[active]` + oauth_browser block;
    DCR client persisted at `oauth/client_us.json`; summary carries /me
    enrichment; orphan-dir guard (`accountDirExists`) on a pre-seeded dir →
    ConfigError.
  - Row 6 redaction: `JSON.stringify(returned tokens)` masks the sentinel
    (CRED-F3); on-disk sentinel appearances ONLY at tokens_{region}.json /
    per-account tokens.json (reveal sites). Python-parity allowlist note: the
    model-invalid exchange branch's `details.response_data` embeds
    `pythonStr(data)` exactly as `flow.py:600-604` does.
- `npx vite-node throwaway/b8-n3/fuzz.ts` → **4 surfaces, 0 divergent**
  (seed=20260816, 500 runs each):
  - A pkce-vs-minimodel: zero-divergence (86/43 lengths, base64url charset,
    challenge == independent sha256/base64url, `challengeFor` == generate's).
  - B parseqs-roundtrip: zero-divergence (quote_plus mini-model encode →
    `parseQs` exact pairs incl. `+`/`&`/`=`/`%`/unicode/𝒳; `pythonUnquote`
    round-trip).
  - C paste-parser: zero-divergence (3 paste forms round-trip; mutated state →
    OAUTH_STATE_MISMATCH).
  - D authorize-url-roundtrip: zero-divergence (param order fixed, S256,
    client_id echo, challenge/verifier linkage through the real login, mask
    discipline on returned tokens).

## CRED-F3 reveal-site status (N3 additions)

N3 adds NO new reveal site: the login path returns `OAuthTokens` (Secret-
wrapped); persistence goes through the N2 sites (`OAuthStorage.saveTokens` for
`persist=true`, `TokenStore.writeTokens` for the orchestrator). `grep -n
"reveal(" packages/node/src/auth/{pkce,callback-server,client-registration,
query-params}.ts src/auth-effects.ts src/index.ts` → zero hits; `flow.ts`
reveal sites are unchanged from N2 (refresh body + getValidToken returns).

## Checks

- `tsc --strict` (node package): clean.
- New Layer-3: 63 tests green (pkce 10, callback 12, registration 13,
  oauth-flow-login 22, auth-effects-bag 6) — plus the intact N1/N2 suites.
- `npm run check`: GREEN — typecheck (all workspaces) + eslint + prettier +
  vitest **231 files / 9,757 tests passed** + browser-bundle smoke OK.
- `npm run conformance` replay: **3,251 passed / 0 failed / 0 unported**
  @ corpus 70c904dc — the 7 `oauth_flow.refresh_tokens` vectors (N2's) stay
  green bound-while-pending; `batch-status.ts` still lists `oauth_flow.` as
  pending (the flip is the GATE's, packet §3.4 last bullet / §5.1 — not
  preempted here).
- No vectors owned by N3 (0).

## TODO(port) triage (P3-2d item)

- `packages/node`: ZERO markers (grep clean, incl. throwaway/b8-n3).
- `packages/core` markers that MENTION B8 and legitimately REMAIN (they
  annotate the core DEFAULT seams, which stay throwing per packet §4.4 "the
  `unportedAuthSeam` helper and the constant STAY in core"): `auth-effects.ts`
  (`unportedAuthSeam` body), `workspace.ts:1182`, `governance-data.ts:62,219`,
  `lifecycle.ts` (B7-era). Their TEXT still reads future-tense ("B8 wires…");
  retexting them is a core touch outside N3's sanctioned budget (§0.3 lists
  exactly two) — left for the gate/arbiter to retext in the flip commit if
  desired. No marker is UNOWNED.

## Outbound notes for the gate / reviewers

- Deferral-header grep: repo-wide `B8` in `packages/*/test` shows only
  historical citations (no open "→ B8" rows). `governance-data.test.ts`'s
  "B8 owns the wiring" line describes the CORE default seam (still true —
  the default throws; the node package supplies `nodeReadFile`).
- throwaway/b8-n3/ stays until arbiter sign-off (gate §5.7 removes it).
