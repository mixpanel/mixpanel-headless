# B9-R1 notes — browser package foundation

**Task**: B9-R1 per `context/phase3/design/b9-packets.md` §1 + §2.
**Started**: 2026-08-16. Model fable. R10.13 incremental protocol.

## Plan (all steps DONE)

1. [x] Read TS repo ground state (core auth, node pkce/flow, browser skeleton, smoke, eslint)
2. [x] TDD: tests first — §2.6 suites + §1.3 node pkce re-point (async-adapt, assertions unweakened)
3. [x] Core `auth/pkce.ts` (WebCrypto, async) + `auth/credential-store.ts` (interface + CREDENTIAL_KEYS)
4. [x] Node migration: `pkce.ts` re-export, `flow.ts` await, suite green (10/10, RED-free migration proven by verbatim assertions)
5. [x] Browser: errors.ts, credential-store.ts, token-serialization.ts, client.ts, index.ts, package.json exports
6. [x] Smoke promotion (two entries) + eslint boundary extension
7. [x] R10.9 harness `throwaway/b9-r1/` + RUN record below
8. [x] npm run check green; corpus HOLD verified; one TS commit; notes commit (Python repo)

## Log

- Read b9-packets.md fully (1004 lines). R1 scope confirmed: zero vectors; contract arbiter R9.3/plan-4.3 where no Python twin.
- Ground-state reads done: node pkce.ts + pkce.test.ts (10 assertions), flow.ts:494 call site,
  core account/session/token/client/workspace seams, eslint boundary block, smoke script,
  browser skeleton, node storage writer shapes (pythonIsoformatDatetimeText / pydanticJsonDatetimeText).

## Design decisions (binding interpretations, for the review pairs)

1. **Path-4 seam (SA gate on session switching)**: packet §2.2 sketches
   `new Workspace({session, client: undefined, clientOptions})`, but §2.3 row 4 demands a
   browser-installed guard on the facade's session replacement and names
   `WorkspaceOptions` as the seam. The ONLY in-memory replacement path that can
   introduce an SA on a browser facade is `MixpanelClient.use({account})` (`Workspace.use`
   goes through resolver seams, which the browser factory leaves at their
   `UNPORTED_RESOLVER_SEAM`-throwing defaults — no sources, no seams, R9.4). Gate
   implemented WITHOUT core edits by building the client in the factory
   (`createMixpanelClient({session, ...clientOptions, fetch: guarded, tokenResolver})`),
   wrapping it in a Proxy whose `use` refuses `account.type === "service_account"`, and
   injecting it via `WorkspaceOptions.client` — the injection point row 4 names. The
   literal `client: undefined` sketch is superseded by row 4's requirement; recorded here
   as the packet-internal reconciliation (no STOP needed: an injection point exists).
2. **R11.9 writer shapes without copying `pydantic-datetime.ts`** (§2.1 rule): browser
   writers re-render datetime text through core `pythonUtcIsoformat(Date.parse(text))`
   (tokens twin, `+00:00`) and the same output with the `+00:00` suffix swapped to `Z`
   (client-info pydantic-JSON twin). Closed-loop contract documented in the module: the
   browser store only writes values whose datetime text it produced itself via
   `pythonUtcIsoformat` over integer-ms clocks (Date.now / injected `now()` — no
   sub-millisecond text can arise). Out-of-grammar / non-UTC-offset text passes VERBATIM
   (node formatters' posture). Narrowing: foreign sub-ms text (e.g. `.000120`) would lose
   digits 4-6 through `Date.parse` — unreachable in the closed loop, disclosed, not
   locked by tests. NO lax read path exists (reads are strict `parseOAuthTokens` /
   `parseOAuthClientInfo`), so the §2.1 STOP condition is not triggered.
3. **Row-3 record shape**: `CREDENTIAL_KEYS.tokens(region)` holds an OAuthTokens JSON
   payload; "persisted record whose parsed account is SA" is interpreted as an
   out-of-band SA-credentials blob written under the tokens key — the gate fires when the
   decoded record carries `type: "service_account"` (checked immediately after JSON.parse,
   before `parseOAuthTokens`/any header use). Same gate re-checked per-request inside the
   store-backed TokenResolver (defense in depth, R2.5 per-request resolution).
4. **Expired-with-refresh in FromStore**: packet specifies expired-with-NO-refresh →
   `OAUTH_TOKEN_ERROR`. Expired WITH refresh: refresh is out of v1 scope (§2.2) and must
   not be silently added, but handing out a known-expired bearer silently is worse — both
   arms throw `OAUTH_TOKEN_ERROR`; the with-refresh arm's message says refresh is browser-v1
   unsupported (re-login or node). `// TODO(port)` + disposition recorded per §2.2.
5. **Security-warning grep test vs the purity boundary**: the eslint block extension covers
   `packages/browser/**/*.ts` INCLUDING tests (same as core), so the §2.6 warning-exists
   test cannot use `node:fs`. It imports the adapter source via vitest's `?raw` module
   (a `raw-text.d.ts` ambient declaration in `packages/browser/test/`), keeping the
   packet's suite placement AND the boundary.
6. **`browserSession` boundary kind**: factory input is caller-supplied params → parse
   with the `param` boundary (ParamValidationError on bad region/projectId), matching the
   R5.5 param-vs-response split for user-facing constructors.
7. **token_env in browser**: `getStaticToken` over an account carrying `token_env` throws
   `OAuthError OAUTH_CONFIG_ERROR` (env is node-only, R9.4 — documented narrowing;
   `browserSession` can only build inline-token accounts, so this arm is reachable only
   via a hand-built session).

## Files landed (TS repo, one commit)

- `packages/core/src/auth/pkce.ts` — NEW: WebCrypto `PkceChallenge` (async `generate`/`challengeFor`) + exported `base64UrlEncodeBytes` (pure table-walk encoder, no Buffer/btoa; R2 consumes it for state generation). Port of `pkce.py:1-73`.
- `packages/core/src/auth/credential-store.ts` — NEW: `CredentialStore` interface + `CREDENTIAL_KEYS` (§2.1 pasted contract verbatim; types + const table only).
- `packages/core/src/auth/index.ts` — barrel exports for both.
- `packages/node/src/auth/pkce.ts` — node:crypto impl RETIRED; documented re-export of core (§1.3.1).
- `packages/node/src/auth/flow.ts` — the single call-site edit: `await PkceChallenge.generate()` (§1.3.2).
- `packages/node/test/pkce.test.ts` — re-pointed (same import path, now transparently core) + async-adapted; ALL 10 assertions verbatim (§1.3.3 zero-behavior-change proof). 10/10 green.
- `packages/browser/src/errors.ts` — `BrowserUnsupportedError` + `BROWSER_SERVICE_ACCOUNT_REFUSED` / `BROWSER_EXPORT_UNSUPPORTED` (browser-local constants, NOT in errors-codes.gen.ts per §2.3).
- `packages/browser/src/credential-store.ts` — `InMemoryCredentialStore` (default; + `clear()` extra), `LocalStorageCredentialStore` (+ `StorageLike` injection seam, default `globalThis.localStorage`, missing-global → `OAUTH_CONFIG_ERROR`); security warning REQUIREMENT text in module + class JSDoc (XSS-readable, origin-scoped, survives logout, bearer readable by any script, in-memory recommended + re-login on reload).
- `packages/browser/src/token-serialization.ts` — R11.9 writer twins (`serializeTokensPayload` +00:00 / `serializeClientInfoPayload` Z) over core `pythonUtcIsoformat` (design decision 2).
- `packages/browser/src/client.ts` — `browserSession`, `createBrowserWorkspace`, `createBrowserWorkspaceFromStore` (§2.2 pasted signatures), SA gates paths 1/3/4, export-refusing fetch guard (origins derived from core `ENDPOINTS` at wrap time), store-backed TokenResolver (per-request re-read, R2.5), `// TODO(port)` on the refresh disposition.
- `packages/browser/src/index.ts` — full §2.5 entry point (skeleton `BROWSER_PACKAGE_NAME` kept).
- `packages/browser/package.json` — `"exports": {".": "./src/index.ts"}` added (core/node have no exports field at all; the packet's explicit instruction to add one to browser wins — recorded as the §2.5 reading).
- `packages/browser/test/{credential-store,token-serialization,sa-refusal,oauth-token-mode,export-refusal}.test.ts` + `helpers.ts` + `raw-text.d.ts` — §2.6 suites, contract-cited headers (R9.3 / plan §4.3), written FIRST (TDD). 54 tests.
- `scripts/browser-smoke.mjs` — two-entry promotion (core + browser; esbuild needs `outdir` for multi-entry even with write:false).
- `eslint.config.js` — purity block extended to `packages/browser/**/*.ts`; both messages updated.

## Refresh disposition (§2.2 record)

Browser v1 ships NO refresh surface. `createBrowserWorkspaceFromStore` (and the per-request
store resolver) throw `OAUTH_TOKEN_ERROR` for EXPIRED tokens in both arms — no-refresh and
with-refresh (the latter's message says refresh is browser-v1 unsupported; silently handing
out an expired bearer was the worse alternative; design decision 4 + TODO(port) in
client.ts). The refresh-token grant twin (`flow.py:442-498`) is the R2 follow-on ONLY under
the D2-ACCEPTED branch (packet §2.2 / §5.5 ledger row 8).

## Layer-3 / check results

- Browser suites: 54/54 green. Node pkce suite: 10/10 green post-migration.
- `npm run check` GREEN end-to-end: typecheck (all workspaces incl. browser), eslint
  (0 errors 0 warnings), prettier, vitest 238 files / 9,886 tests, two-entry browser smoke
  (core + browser, 2,039,209 bytes).
- Corpus HOLD verified early (gate will re-verify): `npm run conformance` =
  **3,251 PASS / 0 FAIL / 0 UNPORTED** @ 70c904dc598d — the §1 node pkce migration did not
  disturb the `oauth_flow.refresh_tokens` vector path.

## R10.9 RUN record (throwaway/b9-r1/ — remove at gate after arbiter sign-off)

| Leg | Command | Count / seed | Result |
|---|---|---|---|
| Mandatory edge set + every error branch | `npx vite-node throwaway/b9-r1/edges.ts` | 32 checks | **32/32, 0 failures** |
| CredentialStore contract fuzz (model = in-memory, SUT = localStorage adapter over StorageLike) | `npx vite-node throwaway/b9-r1/store-fuzz.ts` | 500 runs, fast-check seed 20260816 | **0 divergences** |
| PKCE differential vs live CPython (`uv run python` batched driver, ONE process, JSON on stdin — `pkce_driver.py`) | `npx vite-node throwaway/b9-r1/pkce-differential.ts` | 601 verifiers (LCG seed 20260816; 600 random over base64url alphabet, lengths 43–128, half at the 86-char production shape; + RFC 7636 Appendix-B vector) | **0 divergences** |

Divergence table: EMPTY (all three legs).

Edge-set coverage detail (leg 1): store value edges `"18.0"`, `"1.5"`, `"true"`, `""`, `"𝒳"`
(key AND value; both implementations); empty-key probe (no guard exists in the contract —
both stores treat `""` as an ordinary key; observation recorded); error branches:
`BROWSER_SERVICE_ACCOUNT_REFUSED` ×(paths 1, 3, 4), `BROWSER_EXPORT_UNSUPPORTED` ×3 export
hosts, localStorage-missing `OAUTH_CONFIG_ERROR`, expired-no-refresh AND expired-with-refresh
`OAUTH_TOKEN_ERROR`, absent-tokens `OAUTH_TOKEN_ERROR`, non-JSON-tokens `OAUTH_TOKEN_ERROR`,
malformed-schema + naive-expires_at strict `RESPONSE_VALIDATION_ERROR`, bad-region
`VALIDATION_ERROR` (param boundary), token_env-in-browser `OAUTH_CONFIG_ERROR`, RFC
Appendix-B vector through the browser entry re-export chain.

Boundary self-probe (the §6 R1-5 check, run ahead of review): scratch `node:fs` import
appended to `packages/browser/src/errors.ts` → `eslint` FAILS (no-restricted-imports, 1 hit)
AND the two-entry smoke FAILS; reverted; both green again. The eslint+smoke boundary really
covers packages/browser.

## Tier observation (for the §5.3 model-program rows)

fable ≤ high handled the full shard in one pass; the only mid-flight corrections were
(a) a wrong test expectation (workspace-scoped path is `/workspaces/{wid}/…` per the core
`maybeScopedPath` twin — test fixed to match Python, not the impl), (b) esbuild multi-entry
needing `outdir` with `write:false`, (c) fast-check v4 renaming `fullUnicodeString`
(harness-only). No STOP conditions fired; no core edits beyond the two enumerated touches.

## B9-ARB-A addendum (pair-A arbiter, 2026-08-16 — `b9-reviewA-resolution.md`)

SEM-F1 APPLIED (red-first): the `staticTokenFromAccount` refusal arms in
`packages/browser/src/client.ts` now carry the Python twin's code + details —
`OAUTH_TOKEN_ERROR` with `{account_name, env_var}` for the `token_env` arm
(`token_resolver.py:273-282`) and `{account_name}` for the model-invariant
neither-field arm (`:267-272`), replacing the shipped
`OAUTH_CONFIG_ERROR {field: "token_env"}`. Message text stays
browser-explanatory (R9.4 narrowing; out of contract per R5.4). Two new
Layer-3 rows in `oauth-token-mode.test.ts` lock both arms (details asserted;
zero network captures). Ripple into this notes file's RUN record: the leg-1
edge-set line "token_env-in-browser `OAUTH_CONFIG_ERROR`" is superseded —
`throwaway/b9-r1/edges.ts` expectation updated to `OAUTH_TOKEN_ERROR` with an
inline arbiter cite; harness re-run post-change: **32 checks, 0 failures**
(`npx vite-node throwaway/b9-r1/edges.ts`, same command as the RUN record).

## B9-ARB-B addendum (pair-B arbiter, `b9-reviewB-resolution.md`, 2026-08-16)

Pair-B blind review found two SA-refusal bypasses in this shard's surface —
both fixed red-first (TS commit `de08f1f`):

- **§2.3 path 6 (FB-1, both pair-B lenses)**: `guardClientUse` now traps
  `withProject` and re-wraps derived clients RECURSIVELY; 3 new
  `sa-refusal.test.ts` rows (suite 8 → 11).
- **§2.3 path 7 (FB-2)**: `index.ts` re-exports `Workspace` as **type
  only** (a value export allowed `new Workspace({session: SA})` past both
  gates); 2 new rows.
- FB-9: core `CREDENTIAL_KEYS` gained `all(region)`; both localStorage
  warning sites now name all three payload families; adapter backend
  failures re-throw as coded `OAUTH_CONFIG_ERROR` (FB-11).
- FB-10: core `PkceChallenge.challengeFor`/`generate` throw coded
  `OAUTH_CONFIG_ERROR` when `crypto.subtle` is absent (insecure context);
  new row in `packages/node/test/pkce.test.ts` (suite 10 → 11 rows; the 10
  migrated assertions untouched).

RUN-record status: `edges.ts` **32/0 reproduces unchanged** post-fix (same
command); `store-fuzz` 500 @ 20260816 **0 divergences**; `pkce-differential`
601 @ 20260816 **0 divergences**. See b9-packets.md §10 errata for the
amended §2.3 path table.
