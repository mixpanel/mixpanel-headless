# B9-R2 notes — redirect-based PKCE flow + fetch-pure hoist

Task: b9-packets.md §3 (shard B9-R2). Model fable. 2026-08-16.
TS repo `main` base: 9fcc489 (B9-R1 landed). Python repo: notes-only.

## Progress log

- [x] Packet read fully (§0–§8); R1 surfaces inspected (core pkce/credential-store, browser client/errors/token-serialization/index).
- [x] §3.1 hoist: core `oauth-constants.ts` / `query-params.ts` (git-mv) / `redirect-parse.ts` / `oauth-http.ts`; node re-points (re-export/delegate) — flow.ts, client-registration.ts, callback-server.ts, oauth-constants.ts, query-params.ts.
- [x] §3.2 browser redirect flow (`redirect-flow.ts`: beginLogin/completeLogin) + `registration.ts` (ensureBrowserClientRegistered) + `BROWSER_NO_PENDING_LOGIN` in errors.ts + index.ts appends.
- [x] §3.3 authorize-URL CPython golden (provenance below) — `packages/core/test/auth/oauth-http.test.ts`.
- [x] §3.4 Layer-3 suites (browser: redirect-flow / redirect-attacks / registration / pkce-webcrypto + shared `flow-helpers.ts`); node suites green UNCHANGED (zero test-file edits — the zero-behavior-change proof held on first run: 22+17+13+12+10 across oauth-flow-login / oauth-flow-refresh / client-registration / callback-server / pkce).
- [x] §3.5 harness `throwaway/b9-r2/` + RUN record (below).
- [x] `npm run check` green (243 files / 9,934 tests; two-entry browser smoke OK); corpus spot-check: `npm run conformance` = **3,251 PASS / 0 FAIL / 0 UNPORTED @ 70c904dc** (HOLD confirmed after the hoist — the `oauth_flow.refresh_tokens` vector path now runs through core `postTokenRequest`).

## Hoist mechanics (§3.1) — decisions (arbiter-relevant)

- **`CallbackResult` moved to core `redirect-parse.ts`** WITH `parsePastedRedirect`
  (mechanical necessity: it is the function's return type and is `node:*`-free —
  class body verbatim from `callback-server.ts`, cite `callback_server.py:54-70`);
  node `callback-server.ts` imports + re-exports it so every existing import
  path holds. Documented in both module headers. NOT a §3.1 STOP condition:
  no hidden coupling — the row cannot move without its return type.
- **Core `postTokenRequest` options bag carries `now?`** (epoch-ms) — the packet
  signature omits it but the moved body calls `fromTokenResponse(data, {now})`
  and §7 caution 5 mandates threading the clock seam; node delegates pass
  `this.#now` (previous behavior byte-identical), browser threads §3.2 `now`.
  Mechanical parameterization, disclosed in the oauth-http.ts header.
- **`registerClient(fetchImpl, region, redirectUri, {now?})`** hoists
  `client_registration.py:96-165` (region gate through OAuthClientInfo
  assembly); the cache read/write stays OUTSIDE (node keeps `OAuthStorage`
  wrapper + `saveClientInfo` at `:168`; browser caches via `CredentialStore`
  in `registration.ts`).
- Node `flow.ts` sheds `DEFAULT_TIMEOUT_SECONDS`, `parseQs`, `pythonStrip`,
  lossless-JSON and executor imports (all now used only inside the core
  bodies); `#buildAuthorizeUrl` / `#postTokenRequest` are one-line delegates.
- No STOP condition fired; every row extracted mechanically (byte-diffable
  against the B8 homes modulo `this.#x` → parameter renames).

## Browser-flow decisions (twin-less branches, R9.3 arbiter — documented)

- Parse failures (`OAUTH_PASTE_ERROR` / `OAUTH_AUTH_DENIED` /
  `OAUTH_STATE_MISMATCH`) precede the pending-record delete (§3.2 order:
  parse step 2, delete step 3) — the user can retry with the CORRECT return
  URL; only a successful parse consumes the record. A FAILED exchange after
  the delete does NOT resurrect it (§6 R2-3 lock in redirect-attacks.test.ts).
- Corrupted / non-JSON / wrong-shape pending records → `BROWSER_NO_PENDING_LOGIN`
  (same code as absent; details carry a `reason`). Twin-less: Python holds
  state in-process.
- `ensureBrowserClientRegistered`: a cached client-info record that fails the
  strict `parseOAuthClientInfo` is treated as a cache MISS and re-registered
  (Python's `load_client_info` returns `None` for unreadable cache files).
- completeLogin ALWAYS persists tokens (R9.3 posture — durable only when the
  caller chose the localStorage adapter); pending `created_at` uses the
  R11.9 tokens-twin `+00:00` formatter, client-info payload the pydantic `Z`
  shape (both locked in tests).

## §3.3 golden provenance

Generated 2026-08-16 in the Python repo:

    uv run python -c "from urllib.parse import urlencode; print(
      'https://mixpanel.com/oauth/authorize/?' + urlencode({
        'response_type': 'code', 'client_id': 'cli~ent id+x',
        'redirect_uri': 'https://app.example.com/cb path/ü:1?x=*',
        'state': 'st*ate~/+', 'code_challenge': 'ch/allenge~ =',
        'code_challenge_method': 'S256'}))"

Output pasted verbatim into `packages/core/test/auth/oauth-http.test.ts`
(fixture exercises `~`, space, `+`, `/`, `:`, `*`, `=` and non-ASCII `ü` —
the §3.3 urlencode-vs-URLSearchParams divergence set; `~` stays bare, `*`
percent-encodes: quote_plus rules confirmed byte-exact through the core
`urlEncodePairs` encoder carried UNCHANGED through the hoist).

## R10.9 RUN record (§3.5)

All canned/offline except the two batched `uv run python` differential
drivers (local CPython, no network). Harness at `throwaway/b9-r2/`
(edges.ts, pkce-vectors.ts + pkce_driver.py, redirect-parse-fuzz.ts +
parse_driver.py); removed at the gate after arbiter sign-off (P3-2c).

| Probe | Seed | Cases | Result |
|---|---|---|---|
| §3.5.1 edge set (`edges.ts`): OAUTH_CONFIG_ERROR ×6 (begin+complete × uk/US/""), OAUTH_PASTE_ERROR ×5 (empty, no-code, no-state, garbage, empty-state-value), OAUTH_AUTH_DENIED ±description (incl. non-BMP `𝒳` description decode), OAUTH_STATE_MISMATCH, value edges `"18.0"`/`"1.5"`/`"𝒳"`/`"true"` through state+code fields, BROWSER_NO_PENDING_LOGIN ×3 (absent, replayed, corrupted), OAUTH_TOKEN_ERROR ×7 (network, 400/401 invalid_grant stay generic, 429, 500, non-JSON 200, missing access_token), OAUTH_REGISTRATION_ERROR ×5 (network, 429 w/ retry_after detail, non-success, bad JSON, missing client_id) | n/a (enumerated) | 35 checks | **0 failures** |
| §3.5.2 PKCE RFC vector + CPython differential, THROUGH the browser entry point (`pkce-vectors.ts` → `pkce_driver.py`, one batched `uv run python`) | 20260817 (R1 ran 20260816) | 601 (Appendix-B anchor + 600 random verifiers, half 86-char production shape, half 43–128 RFC range) | **0 divergences** |
| §3.5.3 redirect-parse differential fuzz (`redirect-parse-fuzz.ts` → `parse_driver.py`, fast-check `fc.sample` + one batched `uv run python`; compare code-or-result) | 20260817 | 709 (700 fast-check URL-ish/unicode/%-injection/duplicate-param strings + the 9 TestParsePastedRedirect anchors) | **0 divergences** |

#9/#10 note: pending-record and store payloads are fixed-key objects
(state/verifier/client_id/redirect_uri/created_at) — no integer-like keys,
no ordering contract introduced (§7 caution 7); the fuzz confirms parsed
query pairs are arrays, so the class cannot arise.

## Done-criteria status (§3.7)

- Files on disk; `tsc --strict` clean (all 5 workspaces).
- §3.4 suites green: browser 46 new tests (redirect-flow 22, attacks 10,
  registration 12, pkce-webcrypto 2) + core golden 2; node suites untouched
  and green.
- Smoke green (two-entry: hoisted modules bundle clean for browser).
- `npm run check` green end-to-end; conformance HOLD 3,251/0/0 verified.
- One TS commit (hoist + node re-point + browser flow + tests + harness
  together — no interim dual-home state); this notes commit (Python repo).
- No Python-repo change outside `context/phase3/notes/`.

## Outbound (for D2-SPIKE and the gate)

- D2-SPIKE consumes `registerClient`'s exact body (core `oauth-http.ts`,
  byte-identical to `client_registration.py:106-112` — locked in
  `registration.test.ts`) and the shipped `buildAuthorizeUrl` for its docs
  wording; the §4.3 outcome wording lands in `redirect-flow.ts` JSDoc +
  browser README (owned by the spike task, NOT landed here).
- Browser refresh surface remains out of v1 (§2.2 disposition; Phase-4
  ledger row 8) — `TestOAuthFlowRefresh`/`GetValidToken` exclusions cited in
  redirect-flow.test.ts header.
- Gate: differential regression should note the hoist moved
  `oauth_flow.refresh_tokens`' implementation path into core (suspect list
  §5.1 — spot-verified green here via the full conformance run).

## B9-ARB-B addendum (pair-B arbiter, `b9-reviewB-resolution.md`, 2026-08-16)

Pair-B blind review amended the redirect-flow contract (b9-packets.md §10
errata; all fixes red-first, TS commit `de08f1f`):

- **FB-4**: `beginLogin` validates `redirectUri` (absolute; https or
  http-on-loopback per RFC 8252 §7.3) → `OAUTH_CONFIG_ERROR`; constant-only
  rule documented (JSDoc + README).
- **FB-5**: pending record gains a TTL — `maxPendingAgeMs` (default 30 min,
  exported `DEFAULT_MAX_PENDING_AGE_MS`); expired records refused AND
  consumed (`BROWSER_NO_PENDING_LOGIN`); `created_at` now read + validated.
- **FB-6**: same-realm concurrent `completeLogin` dedup (StrictMode shape:
  identical returnUrl shares ONE exchange; different returnUrl serializes).
- **FB-8**: `completeLogin` strips the URL fragment before
  `parsePastedRedirect` (documented `location.href` input); the CORE parser
  is byte-untouched.
- **FB-7** (docs): redirect flow requires a navigation-surviving store;
  `new LocalStorageCredentialStore(sessionStorage)` named.
- **FB-3** (docs/ledger): `postTokenRequest` `response_data` token-payload
  exposure is Python-parity (`flow.py:596-605`) — no code change; Phase-4
  ledger row 1 re-scoped to `oauth-http.ts:245`; R10.7 Python-first queue
  item filed (`context/phase3/bug-reports/python-oauth-error-details-token-payload.md`).

**RUN-record addendum (edges leg)**: the harness's planted pending records
carried a frozen `created_at: 2026-01-15T10:30:00+00:00`, which the FB-5
TTL now expires against the ambient clock — `throwaway/b9-r2/edges.ts`
stamps `created_at` at run time instead (inline arbiter cite). Re-run:
**35 checks / 0 failures** (same command). `pkce-vectors` 601 @ 20260817
and `redirect-parse-fuzz` 709 @ 20260817 both reproduce with **0
divergences** — the FB-8 strip left the hoisted parser CPython-faithful.
