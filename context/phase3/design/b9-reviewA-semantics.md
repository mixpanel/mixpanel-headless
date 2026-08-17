# B9 pair-A review — lens 1: FLOW/CONTRACT SEMANTICS

**Reviewer**: B9 adversarial reviewer, pair A, lens 1 (fable). 2026-08-16.
**Scope**: all B9 commits — TS `9fcc489` (B9-R1), `009bad7` (B9-R2),
`f6f298b` (B9-D2-SPIKE docs); Python notes/spike commits `5f87491`,
`262e873`, `3005bc9`, `85e3337` — since the B9-DL packet commit `78c37de`.
**Arbiters used**: `flow.py` / `client_registration.py` / `pkce.py` /
`token_resolver.py` where twinned; R9.3 (rulebook `:266-270`) + plan §4.3 +
`b9-packets.md` where browser-only. Citation-for-citation verification.
**Verdict: GO — 0 blocking findings, 1 minor finding, 3 verified-with-note
observations.** Every mandatory §6 check (R1-1..R1-5, R2-1..R2-4) executed;
results below.

## 1. Redirect PKCE flow vs `flow.py` (twinned surfaces)

| Surface | Twin | Result |
|---|---|---|
| Authorize URL params | `_build_authorize_url` (`flow.py:606-635`) → core `oauth-http.ts:74-92` | **MATCH.** Same six params, same insertion order (`response_type, client_id, redirect_uri, state, code_challenge, code_challenge_method`), `scope` omitted (contract, `flow.py:624-626` comment ported), `S256` literal, `{base}authorize/?` shape. Encoder is the B8 `urlEncodePairs` quote_plus twin carried through the hoist unchanged. |
| §3.3 urlencode golden | `oauth-http.test.ts:16-43` | **INDEPENDENTLY RECOMPUTED**: I re-ran the provenance command (`uv run python -c "...urlencode(...)"`) in the Python repo — output byte-identical to the pasted golden, incl. `~` bare, space→`+`, `*`→`%2A`, UTF-8 runs for `ü`. RFC 7636 Appendix-B vector also recomputed via CPython hashlib — matches (R2-2 PASS). |
| Exchange body | `exchange_code` (`flow.py:428-435`) → `completeLogin` step 4 (`redirect-flow.ts:342-358`) | **MATCH field-for-field, order-for-order** (`grant_type, code, redirect_uri, client_id, code_verifier`); byte-compare Layer-3 lock exists (`redirect-flow.test.ts:172-206`, urlencoded body + content-type + `{base}token/` URL). `redirect_uri`/`client_id`/`verifier` come from the pending record persisted at begin-time — correct begin-time binding, matching Python's in-process locals. |
| Token-response classifier | `_post_token_request` (`flow.py:500-605`) → core `postTokenRequest` | **MATCH**: transport-failure branch (details `{url}`), 400/401-only `invalid_grant` probe, REVOKED mapping gated on `operation === "Token refresh"` (exchange keeps the generic code — browser can never hit REVOKED, correct: no refresh surface in v1), non-JSON branch (content-type in message, `{response_body}` details), missing-fields branch (`response_data` via `pythonStr`). Browser network-error rows locked (`redirect-flow.test.ts:334-397`). |
| State generation | `secrets.token_urlsafe(32)` (`flow.py:270`) → `generateState()` (`redirect-flow.ts:169-173`) | **EQUIVALENT**: 32 bytes `crypto.getRandomValues`, base64url-no-pad = 43 chars, same alphabet — the packet §3.2 row-1 spec exactly. Length/alphabet/freshness locked (`redirect-flow.test.ts:159`). |
| Return-URL parse | `_parse_pasted_redirect` (`flow.py:51-115`) → core `redirect-parse.ts:79-124` | **MATCH branch-for-branch**: strip, empty→`OAUTH_PASTE_ERROR`, first-`?` split, `error`→`OAUTH_AUTH_DENIED` (+` — desc` only when non-empty, `:97`), missing code/state→`OAUTH_PASTE_ERROR`, first-element extraction, mismatch→`OAUTH_STATE_MISMATCH`. Backed by the 709-case CPython differential (R2 RUN record, 0 divergences). |
| Region gate | `flow.py:160-165` → `requireBaseUrl` (`redirect-flow.ts:151-160`) | **MATCH** — `OAUTH_CONFIG_ERROR`, sorted-keys message shape. Runs FIRST in both begin and complete, so config-vs-registration error precedence matches Python (ctor gate before DCR). |
| DCR request/branches | `client_registration.py:96-170` → core `registerClient` | **MATCH**: body key order `:106-112` (incl. advisory scope — correctly NOT "fixed" toward the authorize-URL omission, §7 caution 3 both directions honored), 429-before-is_success ordering, 2xx `is_success` twin, `client_id` extraction with the KeyError/TypeError-class fallthrough, `created_at` assembly identical to the B8 node body (`pythonUtcIsoformat(nowMs)` — byte-diffed, see §3). Cache-hit rule in `ensureBrowserClientRegistered`: redirect_uri must match (`:92-93`), cache check BEFORE region gate (Python order) — both locked in `registration.test.ts`. |

Browser-only adaptations verified against the packet contract: begin/complete
split order (region gate → DCR → PKCE+state → persist pending → authorize URL)
= §3.2 numbered steps verbatim; pending record `{state, verifier, client_id,
redirect_uri, created_at}` with R11.9 tokens-twin `created_at` (+00:00) =
§3.2 payload spec; tokens ALWAYS persisted at step 5 (R9.3 posture);
`BROWSER_NO_PENDING_LOGIN` only on the genuinely twin-less branch.

**R2-3 (single-use ordering)**: delete executes AFTER a successful parse and
BEFORE the exchange (`redirect-flow.ts:333-339`) — packet steps 2/3 in order.
The failure branch is right both ways: parse failure (incl. state mismatch)
precedes the delete so the user can retry with the CORRECT url (packet step
ordering; locked `redirect-attacks.test.ts:78`), and a FAILED exchange does
NOT resurrect the record (locked `redirect-attacks.test.ts:161`). Replay of a
consumed URL → `BROWSER_NO_PENDING_LOGIN` (`redirect-flow.test.ts:280`).
Cross-region key isolation locked (`:301`). PASS.

## 2. PKCE-placement ruling execution (§1) — VERIFIED

- **One implementation**: `packages/core/src/auth/pkce.ts` (WebCrypto,
  async). `packages/node/src/auth/pkce.ts` is a 1-line documented re-export;
  no second implementation anywhere (grepped for `createHash`/sha256 in
  browser+core auth: none outside the core impl).
- **Encoder audit (R1-2)**: `base64UrlEncodeBytes` is a pure table walk over
  the RFC 4648 §5 alphabet (`-`/`_`), pads never emitted (3-byte grouping
  with null sentinels — no `=` in any branch), byte-safe 0-255, no `Buffer`,
  no `base64EncodeUtf8` reuse (the §1.2 trap is explicitly documented at the
  alphabet const). Verified against the Appendix-B vector (recomputed) and
  the 601-verifier CPython differential (R1 RUN record, 0 divergences).
  Boundary case `i+1 == length` handled via `(b1 ?? 0) >> 4`. PASS.
- **86-char verifier lock**: `secrets.token_bytes(64)` twin
  (`getRandomValues(new Uint8Array(64))`), locked at
  `packages/node/test/pkce.test.ts` AND through the browser entry
  (`pkce-webcrypto.test.ts:21-27` — 86/43 + alphabet).
- **R1-1 assertion-survival diff**: full `diff` of `4095f46:pkce.test.ts` vs
  HEAD — every edit is `async`/`await` adaptation or comment text; all 10
  assertions (9 translated rows + RFC vector) survive verbatim; expected-hash
  computation unchanged (node:crypto in the node-homed test file — legal).
  PASS.
- **Zero behavior change for node, proven**: `flow.ts:422` single `await`;
  untouched B8 suites green (`oauth-flow-login` 22, `oauth-flow-refresh` 17,
  `client-registration` 13 — I re-ran them); **`npm run conformance` re-run
  by this reviewer: 3,251 PASS / 0 FAIL / 0 UNPORTED @ 70c904dc** — the
  `oauth_flow.refresh_tokens` vector path (prime suspect per §5.1) holds.

## 3. Hoist honesty (R2-1) — VERIFIED

Byte-diffed every §3.1 row against its `4095f46` B8 home:
`query-params.ts` (header comments only), `oauth-constants.ts` (header +
`DEFAULT_SCOPE` joined from `client-registration.ts` — value identical),
`parsePastedRedirect` + `CallbackResult` (mechanical move, bodies verbatim;
the `CallbackResult` co-move is disclosed as a HOIST NOTE in the module
header + R2 notes), `#buildAuthorizeUrl` → `buildAuthorizeUrl` (body verbatim,
`this.#baseUrl` → param), `#postTokenRequest` → `postTokenRequest` (body
verbatim; `this.#fetchImpl`/`this.#now`/`this.#baseUrl` → parameters, the
`now` addition disclosed in the module-header HOIST NOTE; node delegate
threads `this.#now` so node behavior is bit-identical), DCR POST half
(`created_at: pythonUtcIsoformat(nowMs)` identical to the B8 body at
`4095f46:client-registration.ts:207-213`; cache read/write correctly left
OUTSIDE the hoist in both runtimes). Node suites unweakened (diff-checked
zero test-file changes besides `pkce.test.ts`). No §3.1 STOP-condition
trigger observed — every row was in fact mechanical. PASS.

## 4. CredentialStore contract completeness — VERIFIED

Interface + `CREDENTIAL_KEYS` in core match the §2.1 pasted contract
member-for-member (get/set/delete, `Promise|direct` union, `null`-not-
`undefined` absent contract with the `client_registration.py:92-93` cite,
three key builders with the exact `mp.tokens.` / `mp.oauth_client.` /
`mp.pending_login.` namespaces). Per-region narrowing documented in the
module header as required. Implementations: `InMemoryCredentialStore`
(Map; `clear()` extra — §2.1-allowed), `LocalStorageCredentialStore`
(injected `StorageLike`, default `globalThis.localStorage`, missing-global
`OAUTH_CONFIG_ERROR`). **R1-4**: the security warning exists at BOTH module
and class JSDoc and covers all required elements — synchronous, origin-
scoped, XSS-readable ("readable by any script on the origin"), survives
logout unless deleted, in-memory default recommended with re-login on
reload; warning-exists source-text test present
(`credential-store.test.ts`). R11.9 writer shapes: tokens `+00:00` /
client-info `Z`, both via core `pythonUtcIsoformat`, no `pydantic-datetime`
copy, strict read paths, closed-loop narrowing documented — locked in
`token-serialization.test.ts` (10 green). PASS.

## 5. SA-refusal path hunt (R1-3) — NO SIXTH PATH FOUND

Attempts to reach `accountAuthHeader`/Basic with a `service_account` on a
browser-factory-built facade:

1. `createBrowserWorkspace({session: saSession})` → gated at the FIRST
   statement (`client.ts:422-425`). Locked.
2. `browserSession(...)` → type-level cannot express SA (options carry only
   `token`); `@ts-expect-error` fixture present. Locked.
3. SA-shaped store record → `readStoredTokens` refuses immediately after
   `JSON.parse`, before parse/header use (`client.ts:187-195`); the
   per-request store resolver RE-RUNS this gate on every request (R2.5) —
   stronger than the packet asked. An SA-shaped record WITHOUT `type:` fails
   the strict `parseOAuthTokens` and never yields Basic material. Locked.
4. `client.use({account: SA})` → Proxy guard rejects, prior session
   retained (atomic-on-failure); `Workspace.use` routes through
   `this.client` = the proxy, and its account-by-name arm dies earlier at
   the `UNPORTED_RESOLVER_SEAM` defaults (no `sources` in browser —
   verified `workspace.ts:1300-1349` + `sa-refusal.test.ts:146`). Locked.
5. R2 flow functions take no `Account` — compile-time excluded, documented
   in the module header. Locked.
6. **Hunt extras**: (a) `clientOptions.tokenResolver` injection — resolver
   output is only ever used as `Bearer ${token}`; cannot mint Basic. (b)
   Entry-point audit: `packages/browser/src/index.ts` re-exports `Workspace`
   but NOT `parseAccount`/`parseSession`/`createMixpanelClient`, and
   `Session`/`Account` are type-only — an SA `Session` value cannot be
   constructed through the browser entry point at all; deep-importing
   `packages/core` internals is outside the browser build surface (R9.3
   binds the browser build). (c) `clientOptions` is
   `Omit<MixpanelClientOptions,"session">` — no session smuggling.

No blocking path. The refusal message satisfies R9.3's "explanatory": names
the received type, the WHY (long-lived Basic secrets vs browser origin,
CORS-would-permit note with the plan §4.3 Tier C cite), and both supported
alternatives; assertions key on `BROWSER_SERVICE_ACCOUNT_REFUSED` (R5).
Export exclusion (§2.4): origin set derived from core `ENDPOINTS` at wrap
time (no restated literals), coded rejection before network, guard wraps the
INJECTED fetch — (a)/(b)/(c) locked in `export-refusal.test.ts` (7 green).

## 6. `oauth_token` mode vs Python semantics — VERIFIED (1 minor finding)

`browserSession` builds the account via core `parseAccount({type:
"oauth_token", ...}, {boundary: "param"})` and the session via
`parseSession` — never hand-assembled (P3-5 rule-3 analogue honored); the
Bearer header is produced by the CORE header path and locked byte-exact
(`oauth-token-mode.test.ts`: `Authorization: Bearer tok-123` captured off
the transport; workspace-pinned `maybe_scoped_path`
`/api/app/workspaces/789/dashboards` re-used, not re-implemented; non-digit
projectId → `ParamValidationError` at the param boundary). Default name
`"browser"`, region literal union, optional workspaceId — all §2.2. PASS.

**FINDING F1 (MINOR, code-choice divergence from nearest twin)**:
`staticTokenFromAccount` (`packages/browser/src/client.ts:130-144`) refuses a
`token_env`-carrying `oauth_token` account with `OAUTH_CONFIG_ERROR`,
details `{field: "token_env"}`. Python's nearest twin branch —
`get_static_token` with an unusable `token_env`
(`token_resolver.py:273-282`) — raises **`OAUTH_TOKEN_ERROR`** with details
`{account_name, env_var}`. The browser condition is arguably twin-less
("env reading impossible in this runtime" vs "env var unset"), the JSDoc
carries the R9.4 narrowing cite, R2-4's letter is satisfied
(`OAUTH_CONFIG_ERROR` is a Python-cited code), and the arm is reachable
only via a hand-built session (`browserSession` cannot express
`token_env`). Still: a caller porting node code that keys on
`OAUTH_TOKEN_ERROR` for "static token unresolvable" sees a different code
in browser. Recommend the arbiter either bless the narrowing explicitly in
the R1 notes ledger or align the code to `OAUTH_TOKEN_ERROR`. Non-blocking.

## 7. Spike artifacts (flow/contract angle only; the spike has its own reviewer)

Docs commit `f6f298b` lands the §4.3-ACCEPTED wording VERBATIM per §9
(README `packages/browser/README.md:19-31` + `redirect-flow.ts` JSDoc);
the §4.5 residual-gap triple appears verbatim and the docs claim no e2e
verification. README leads with `oauth_token` (§8 traceability row
honored); fallback correctly NOT triggered while `oauth_token` stays
first-class. OBSERVATION (non-finding, packet-authored text): the sentence
"end-to-end browser consent/exchange verified in Phase-4 live burn-in" can
be misread as a past-tense claim; the very next paragraph disclaims it
explicitly, and the wording is packet-§4.3-verbatim — flagging only for the
Phase-4 wording pass, not against this batch.

## 8. Other verifications and observations

- **R2-4 error-code audit**: exhaustive grep of browser src + hoisted core
  modules — every thrown code is Python-cited (`OAUTH_CONFIG_ERROR`,
  `OAUTH_PASTE_ERROR`, `OAUTH_AUTH_DENIED`, `OAUTH_STATE_MISMATCH`,
  `OAUTH_TOKEN_ERROR`, `OAUTH_REGISTRATION_ERROR`, `OAUTH_REFRESH_REVOKED`)
  or an enumerated `BROWSER_*` constant (3, all in `errors.ts`, correctly
  kept OUT of `errors-codes.gen.ts`). No ad-hoc strings. PASS.
- **R1-5 boundary scratch test (executed by this reviewer)**: appended a
  scratch `import ... from "node:fs"` to `packages/browser/src/errors.ts`;
  `scripts/browser-smoke.mjs` FAILED (esbuild could-not-resolve at the
  browser entry) AND `npx eslint` FAILED (no-restricted-imports with the
  extended R9.3/§0.4 message); reverted; smoke re-verified green; tree
  clean. Both checks demonstrably cover `packages/browser`. PASS.
- **OBSERVATION O-A (verified, disclosed — no action)**: the §2.2 pasted
  prose said `new Workspace({session, client: undefined, clientOptions})`;
  the implementation instead assembles the client itself and injects it via
  `WorkspaceOptions.client` (Proxy `use` guard + guarded fetch). This is
  exactly the §2.3 row-4 sanctioned mechanism ("installs the check WITHOUT
  modifying core" through the `WorkspaceOptions` seam), is disclosed in the
  R1 notes, changes no end-user signature, and no core edit occurred
  (verified: `git diff 4095f46..f6f298b -- packages/core/src/workspace.ts
  packages/core/src/client/client.ts` is empty). Not a deviation from
  contract — the packet's row 4 supersedes its own §2.2 sketch line.
- **OBSERVATION O-B (verified, no action)**: concurrent `beginLogin` calls
  for one region last-write-win the pending record; the earlier attempt's
  return then fails `OAUTH_STATE_MISMATCH` (record intact) or, after the
  winner completes, `BROWSER_NO_PENDING_LOGIN`. Packet is silent; the CSRF
  property is preserved in every interleaving I could construct.
- **Refresh discipline**: no refresh grant anywhere in browser (grep
  `refresh_token` in browser src: only the persisted-payload passthrough and
  the expired-tokens hint) — the §2.2 disposition held, `TODO(port)` marks
  the D2-ACCEPTED follow-on, Phase-4 ledger row 8 exists.
- **Harness spot-checks**: both CPython differentials use ONE batched
  `uv run python` driver (hook discipline); RUN records carry seeds/counts
  (R1: fc seed 20260816, 601 verifiers; R2: 20260817, 601 + 709), all
  0-divergence claims consistent with the committed drivers.
- **Suite/tooling state re-verified by this reviewer**: 164/164 green
  across the 15 browser/core-auth/node-auth suites; `npm run lint` clean;
  `npm run typecheck --workspaces` clean; two-entry smoke green;
  conformance 3,251/0/0.

## 9. Findings summary (for the arbiter)

| # | Severity | Where | What |
|---|---|---|---|
| F1 | MINOR | `packages/browser/src/client.ts:130-144` | `token_env` refusal code `OAUTH_CONFIG_ERROR` diverges from the nearest Python twin `OAUTH_TOKEN_ERROR` (`token_resolver.py:273-282`), details shape differs too; bless-or-align. |

GO for lens 1. No blocking findings; F1 is the only item requiring an
arbiter decision.
