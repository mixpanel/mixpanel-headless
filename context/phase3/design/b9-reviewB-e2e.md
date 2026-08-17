# B9 pair-B (BLIND) — lens 2: adversarial END-TO-END review

**Task**: B9-REV-B2 · fable · 2026-08-16. Doubled-review pair B, lens 2
(P3-3 auth doubling; `b9-packets.md` §6). **Blind posture honored**: no
`b9-reviewA-*` file was opened at any point (orchestrator ruling —
per-shard doubling satisfied at BATCH level; blindness = the do-not-read
rule over pair-A artifacts). Inputs used: the TS diff `4095f46..HEAD`
(both repos), the Python sources (`flow.py`, `client_registration.py`,
`pkce.py`, `storage.py`), rulebook **R9.3** (`:266-270`), plan **§4.1** /
**§4.3**, and `b9-packets.md` (contract text — read for the pasted
signatures/step tables that ARE the contract where no Python twin
exists).

**Verdict: NO-GO pending F1** (one blocking SA-refusal escape, pre-declared
blocking by `b9-packets.md` §6 check R1-3), plus 2 major and 3 minor
findings. Everything else I simulated is faithful: 46 e2e checks over 9
flow sets, all cross-runtime request diffs byte-identical, both shard R10.9
RUN records reproduced exactly, corpus HOLD re-verified.

## 1. Method

Hand-rolled DOM-free browser simulation (the packages touch no DOM global
— verified by grep: only `globalThis.localStorage` inside the adapter and
`globalThis.fetch` defaults), driven through the SHIPPED entry point
`packages/browser/src/index.ts`. Every scenario runs against a recording
`fetch` double that captures method/url/headers/body; a canned IdP serves
`mcp/register/` and `token/`. Page navigation is simulated by discarding
the JS objects of "page load 1" and constructing fresh ones in "page load
2" (exactly what a redirect does).

Drivers (review artifacts, TS repo — the `b8-reviewB-e2e` precedent;
**the B9 gate must delete `throwaway/b9-reviewB-e2e/` along with
`throwaway/b9-r1`+`b9-r2`**):

```
throwaway/b9-reviewB-e2e/harness.ts        # recording fetch + scenario ledger
throwaway/b9-reviewB-e2e/r1-token-mode.ts  # oauth_token happy path + parity + export
throwaway/b9-reviewB-e2e/r2-redirect.ts    # PKCE round trip + 8 adversarial variants
throwaway/b9-reviewB-e2e/r3-race.ts        # double-invoke vs a single-use-code IdP
throwaway/b9-reviewB-e2e/r4-sa-refusal.ts  # SA paths 1/3/4 + independent path hunt
throwaway/b9-reviewB-e2e/r5-parity.ts      # browser-vs-node request diffs
throwaway/b9-reviewB-e2e/r6-store.ts       # store lifecycle, rotation, DCR cache, adapter
throwaway/b9-reviewB-e2e/r7-returnurl.ts   # return-URL shapes + persist-failure tail
throwaway/b9-reviewB-e2e/r8-edges.ts       # token_env arms, degenerate tokens
throwaway/b9-reviewB-e2e/r9-navigation.ts  # full page-navigation simulation
```

Run: `npx vite-node throwaway/b9-reviewB-e2e/<file>.ts` (all offline;
CPython cross-checks via one batched `uv run python -c`).

## 2. Scenario ledger (46 checks; 6 FAIL → findings F1–F5)

| Set | Scenario | Result |
|---|---|---|
| F1/F1b | `oauth_token` app + query-host calls: `Authorization: Bearer tok-abc`, UA, `query_origin` | PASS |
| F2 | browser vs directly-built core client: method/url/headers/body **byte-identical** | PASS |
| F3 ×3 | export hosts us/eu/in refused `BROWSER_EXPORT_UNSUPPORTED`, zero inner fetches | PASS |
| F4 | `workspaceId` → `/api/app/workspaces/42/flags` via the real `maybeScopedPath` | PASS |
| F5 | injected-fetch `TypeError` → `HTTP_ERROR` (R2.10 adapter intact under the guard wrap) | PASS |
| F6a–f | begin→navigate→complete→store-backed workspace: authorize-URL shape (scope omitted), pending record, exchange body field-for-field (`flow.py:428-434`), tokens persisted `+00:00`, bearer on the wire | PASS |
| F7/F7b | wrong state → `OAUTH_STATE_MISMATCH`, no token POST, pending survives, honest return still completes | PASS |
| F8 | `error=access_denied&error_description=…` → `OAUTH_AUTH_DENIED` with description | PASS |
| F9 | replay of a consumed return URL → `BROWSER_NO_PENDING_LOGIN` | PASS |
| F10 | FAILED exchange does not resurrect state (second attempt → NO_PENDING) — §6 R2-3 | PASS |
| F11 | store swap mid-flow → `BROWSER_NO_PENDING_LOGIN` | PASS |
| F12 | two same-region tabs: second `beginLogin` wins, first tab's return → state mismatch | PASS |
| F13 | cross-region concurrency isolated (us+eu both complete; eu host correct) | PASS |
| **F14 / R3** | **double-invoked `completeLogin` (React StrictMode shape): 2 token POSTs; against a single-use-code IdP one call rejects `OAUTH_TOKEN_ERROR` although login succeeded** | **FAIL → F2** |
| P1/P3/P4/P4b/P4c | SA refusal paths 1, 3, 4 coded + prior session survives; `ws.use({account})` blocked by the unported resolver seam | PASS |
| **H1** | **`ws.client.withProject("999").use({account: SA})` succeeds and puts `Basic c2EudXNlcjpodW50ZXIy` on the wire to `https://mixpanel.com/api/app/...`** | **FAIL → F1** |
| H2 | the export guard DOES survive `withProject` (fetch threading intact) | PASS |
| H3 | `clientOptions` cannot install an SA | PASS |
| R5a/b/c | DCR POST, token-exchange POST, authorize URL: **node delegate vs browser identical** (byte diff over method/url/body/headers) | PASS |
| R5d | state: 43-char base64url, 25/25 unique (`token_urlsafe(32)` twin) | PASS |
| R5e | RFC 7636 Appendix-B vector identical through core + node entry points | PASS |
| R6a–d | per-request re-resolution: rotation picked up, expiry re-fires, wiped store, SA planted mid-session all coded | PASS |
| R6e/f | node-written `tokens.json` bytes readable by the browser store; writer↔strict-reader closed loop | PASS |
| R6g/h | DCR cache hit iff `redirect_uri` matches (`client_registration.py:92-93`); client-info `created_at` in the `Z` shape | PASS |
| **R6i** | **`LocalStorageCredentialStore.set` under quota exhaustion leaks a raw `DOMException` (no `.code`)** | **FAIL → F5** |
| R6j | missing `globalThis.localStorage` → `OAUTH_CONFIG_ERROR` | PASS |
| **R7a** | **`completeLogin({returnUrl: location.href})` with a hash route (`…?code=C&state=S#/dashboard`) → `OAUTH_STATE_MISMATCH`** | **FAIL → F4** |
| R7b/c | duplicate `code` → first wins; `+` decodes to space — CPython `parse_qs` parity confirmed live | PASS |
| R7d/e/f | blank return → `OAUTH_PASTE_ERROR`; forged state w/o pending → NO_PENDING and zero POSTs; corrupted record → NO_PENDING | PASS |
| **R7g** | **6-year-old pending record accepted — `created_at` is written but never read (no TTL)** | **FAIL → F6** |
| **R7h** | **persist failure after a successful exchange: uncoded `DOMException`, code already burned, tokens dropped** | **FAIL → F5 (amplifier)** |
| R8a | `token_env` account in a browser build → `OAUTH_TOKEN_ERROR` naming the env var | PASS |
| R8b | `oauth_browser` session with an empty store → `OAUTH_TOKEN_ERROR`, zero network | PASS |
| R8c | `token: ""` accepted → `Authorization: Bearer` — **matches Python** (`OAuthTokenAccount.token: SecretStr` has no min_length; probe run) → observation only | PASS (parity) |
| R8d | `browserSession` field spellings (R7.6) | PASS |
| **R9a** | **redirect PKCE with the R9.3 DEFAULT in-memory store cannot complete after a real navigation (always `BROWSER_NO_PENDING_LOGIN`)** | **FAIL → F3** |
| R9b | same flow with the localStorage adapter completes across the navigation | PASS |

## 3. Findings

### F1 — BLOCKER · sixth SA ingress path: `withProject()`-derived clients are unguarded

`createBrowserWorkspace` installs the SA refusal on `client.use` through a
Proxy (`client.ts:325-342`). The Proxy forwards every other member via
`Reflect.get`, so `withProject` returns a **raw core client**
(`packages/core/src/client/client.ts:1166-1193` builds it with
`createMixpanelClient`, no guard) whose `use({account})` reaches
`accountAuthHeader` (`account.ts:584-587`) with a `service_account`.

Repro (`r4-sa-refusal.ts` H1, reproduced verbatim):

```
const ws = createBrowserWorkspace({ token: "t", projectId: "12345", region: "us", fetch });
const derived = ws.client.withProject("999");
await derived.use({ account: saAccount });   // NO refusal
await derived.currentAuthHeader();           // "Basic c2EudXNlcjpodW50ZXIy"
await derived.appRequest("GET", "/projects/999/dashboards");
// wire: authorization: Basic c2EudXNlcjpodW50ZXIy → https://mixpanel.com/api/app/projects/999/dashboards
```

`b9-packets.md` §6 R1-3 pre-declares this class blocking ("attempt to
construct a browser workspace/header path that reaches `accountAuthHeader`
with a `service_account` without hitting a §2.3 gate — success = blocking
finding"), and R9.3 mandates refusal *at runtime in browser builds*. The
shipped README also asserts refusal "**on every path**"
(`packages/browser/README.md:17`), which this falsifies. `Workspace.client`
is public (`workspace.ts:1105`) and `withProject` is the documented
multi-project escape hatch, so no private API is involved; the SA `Account`
comes from `@mixpanel-headless/core` (`parseAccount`), which every
isomorphic app already imports — the exact shared-auth-module scenario R9.3
exists for. Note the export guard DOES survive `withProject` (H2), so the
gap is specific to the `use`/auth axis.

Suggested fix (no core edit needed, matching the §2.3 path-4 mechanism):
have the browser guard wrap `withProject`'s return value with the same
guard recursively (`guardClientUse(target.withProject(...))`), and add a
Layer-3 row to `sa-refusal.test.ts` (currently paths 1/2/3/4 only —
`sa-refusal.test.ts:48-160`). If the arbiter prefers, an equally small
alternative is refusing `withProject` outright in browser builds with
`BROWSER_*` code; either way the escape must close or the README claim must
be narrowed with an arbiter-blessed disclosure.

### F2 — MAJOR · the single-use pending-state lock does not hold under concurrent `completeLogin`

`completeLogin` reads the pending record (step 1), parses (2), then deletes
(3) — three awaits apart (`redirect-flow.ts:327-339`). Two concurrent calls
both observe the record before either deletes, so both exchange the same
code.

Repro (`r3-race.ts`, IdP enforcing RFC 6749 §4.1.2 single-use codes):

```
const ret = `https://app.example.com/cb?code=CODE-RACE&state=${state}`;
await Promise.allSettled([completeLogin({...ret}), completeLogin({...ret})]);
// tokenPosts: 2 ; outcomes: ["ok", "OAUTH_TOKEN_ERROR"]
```

Reachability is high, not theoretical: React 18 StrictMode double-invokes
effects, and the return page's "exchange the code" effect is precisely the
double-invoked shape; the user sees a spurious `OAUTH_TOKEN_ERROR` after a
login that actually succeeded (and a second, wasted `token/` POST hits the
IdP). Contract: `b9-packets.md` §3.2 step 3 states the lock unqualified
("a second `completeLogin` with the same URL hits branch 1; replay-attack
lock") and §6 R2-3 makes the ordering a mandatory reviewer check.
Suggested fix: make the consume atomic — read-and-delete before the parse
is wrong (it breaks the F7 wrong-state recovery), so either keep a
module-level in-flight promise keyed by `pendingLogin(region)` (idempotent
second call returns the same promise) or re-read-and-compare after the
delete and abort when the record changed; add a concurrency row to
`redirect-flow.test.ts`.

### F3 — MAJOR · redirect PKCE cannot complete with the R9.3 DEFAULT store, and nothing says so

R9.3 mandates BOTH "default in-memory" and "redirect-based PKCE". The
redirect destroys the heap, so a `beginLogin` whose store is the shipped
default (`InMemoryCredentialStore`) is guaranteed to fail at
`completeLogin` with `BROWSER_NO_PENDING_LOGIN` — 100 % of the time, not an
edge case (`r9-navigation.ts` R9a vs R9b). The only shipped store that
works across the navigation is `LocalStorageCredentialStore`, i.e. the one
carrying the XSS security warning; no `sessionStorage` adapter exists.

The docs do not state this anywhere a reader will meet it: the README PKCE
section (`README.md:20-42`) never mentions a store requirement, the
"Credential storage" section recommends the in-memory default without
qualification (`README.md:44-50`), and `beginLogin`'s own `@example` passes
a bare `store` (`redirect-flow.ts:186-194`). The nearest text — the module
header row "in-memory default = no durable persistence" — states the
mechanism, never the consequence.

Suggested fix (docs + one ergonomic guard, no contract change): say
explicitly in the README PKCE section and in `beginLogin`'s JSDoc that the
redirect flow REQUIRES a store that survives navigation, recommend
`sessionStorage` (a `StorageLike` the existing adapter already accepts:
`new LocalStorageCredentialStore(sessionStorage)` — worth naming, since it
narrows the XSS exposure window), and consider a `SessionStorage…` alias.
An arbiter may also want `beginLogin` to warn when handed a store instance
that is `InMemoryCredentialStore`.

### F4 — MINOR · the documented `returnUrl: location.href` breaks under a hash router, and reports it as CSRF

`parsePastedRedirect` splits on the first `?` and hands the remainder to
`parseQs` — no fragment strip (`redirect-parse.ts:92-94`), faithful to
`flow.py:90-92`. In the browser the documented input is `location.href`
(`redirect-flow.ts:310-316`), so an SPA with a hash router produces
`…?code=C&state=S#/dashboard` → `state === "S#/dashboard"` → mismatch:

```
completeLogin({ returnUrl: "https://app.example.com/cb?code=C1&state=<state>#/dashboard" })
// OAuthError OAUTH_STATE_MISMATCH — "does not belong to this login session"
```

CPython parity confirmed live (`parse_qs('code=C1&state=XYZ#/dashboard')` →
`{'code': ['C1'], 'state': ['XYZ#/dashboard']}`), so this is NOT a Python
divergence — it is a browser-adaptation gap the node twin never had
(its redirect target is a bare localhost callback). The user-visible
symptom is a security-flavoured error for a benign URL shape.
Suggested fix: document `returnUrl: location.search` (or strip the
fragment in `completeLogin` before parsing, keeping the shared core parser
untouched — the hoisted function must stay a `flow.py` twin).

### F5 — MINOR · the shipped localStorage adapter leaks uncoded `DOMException`s

`LocalStorageCredentialStore.set/get` forward to the backend unguarded
(`credential-store.ts:165-186`), so Safari private mode / quota exhaustion
surfaces a raw `DOMException` with no `.code` — inconsistent with R5 (and
with the class's own constructor, which codes `OAUTH_CONFIG_ERROR`). Repro:
`r6-store.ts` R6i → `{"code":null,"cls":"DOMException","message":"quota exceeded"}`.
Amplifier (`r7-returnurl.ts` R7h): when the throw lands at `completeLogin`
step 5, the authorization code has already been redeemed and the pending
record deleted, so the successfully-obtained tokens are discarded and the
caller must restart the whole login — with an error that carries no code to
branch on. Suggested fix: wrap the adapter's three methods and re-throw as
a coded error (`OAUTH_CONFIG_ERROR` or a `BROWSER_*` constant), and
document/decide whether `completeLogin` should return the tokens when only
the persist leg failed.

### F6 — MINOR · pending-record `created_at` is written but never read (no TTL)

`beginLogin` stamps `created_at` (`redirect-flow.ts:223`), and
`loadPendingRecord` validates only `state`/`verifier`/`client_id`/
`redirect_uri` (`redirect-flow.ts:279-283`). A pending record from 2020 is
accepted in 2026 (`r7-returnurl.ts` R7g). Consequences: an abandoned login
leaves a PKCE verifier at rest in localStorage indefinitely, and the
`created_at` field is dead weight. The packet mandates the field but no TTL,
so this is a disclosure/hardening call, not a contract breach. Suggested
fix: either enforce a bounded lifetime (reject + delete beyond, say, 10
minutes — the value already exists and `now` is already threaded) or
document explicitly that the record is never expiry-checked and callers
should clear it on logout.

## 4. Mandatory-check execution (P3-2(d) items 1–5 + §6 B9 checks)

- **Item 5 / harness re-run — REPRODUCED EXACTLY** from the recorded
  commands and seeds: `b9-r1/edges.ts` → 32 checks / 0 failures;
  `b9-r1/store-fuzz.ts` → 500 runs @ seed 20260816 / 0 divergences;
  `b9-r1/pkce-differential.ts` → 601 verifiers @ seed 20260816 / 0
  divergences; `b9-r2/edges.ts` → 35 checks / 0 failures;
  `b9-r2/pkce-vectors.ts` → 601 @ seed 20260817 / 0; `b9-r2/redirect-parse-fuzz.ts`
  → 709 @ seed 20260817 / 0. Every count matches the RUN records in
  `B9-R1-notes.md` / `B9-R2-notes.md`.
- **§6 R1-5 boundary probe (both ways, executed and reverted)**: a scratch
  `import { readFileSync } from "node:fs"` in
  `packages/browser/src/errors.ts` fails eslint
  (`no-restricted-imports`, the extended `packages/browser/**` block) AND
  fails `node scripts/browser-smoke.mjs` (esbuild resolve error). Reverted;
  `git diff` clean.
- **§6 R2-4 error-code audit** (my own sweep of the browser+hoisted
  sources): every thrown code is a `flow.py`-cited Python code
  (`OAUTH_CONFIG_ERROR`, `OAUTH_PASTE_ERROR`, `OAUTH_AUTH_DENIED`,
  `OAUTH_STATE_MISMATCH`, `OAUTH_TOKEN_ERROR`, `OAUTH_REGISTRATION_ERROR`)
  or one of the three enumerated `BROWSER_*` constants — with the single
  exception in F5 (an unwrapped host `DOMException`).
- **R5/regression state**: `npm run conformance` → **3,251 PASS / 0 FAIL /
  0 UNPORTED @ 70c904dc** (HOLD intact after the §1 pkce migration and the
  §3.1 hoist); `vitest run` over `packages/browser` + the affected
  node/core auth suites → 26 files / 331 tests green.
- **Parity (this lens's core duty)**: DCR POST, token POST, authorize URL
  and the PKCE RFC vector are byte-identical between the node and browser
  entry points (R5a–R5e), and a browser workspace's Query/App requests are
  byte-identical to a directly-built core client's (F2) — the hoist did not
  fork behavior.

## 5. Observations (no action requested)

1. `token: ""` builds a session that sends a bare `Authorization: Bearer`;
   Python's `OAuthTokenAccount` accepts an empty `SecretStr` identically
   (probe run), so R10.6 says leave it.
2. Per-request token resolution is genuinely per-request: rotation,
   expiry, deletion and an out-of-band SA plant all take effect on the
   NEXT call (R6a–d) — this is stronger than the packet's construction-time
   wording and is the right posture.
3. `parse_qs` browser-relevant corners (duplicate params, `+`→space) match
   CPython exactly; the #9/#10 integer-key class cannot arise (parsed pairs
   are arrays), as the R2 notes claim.
4. The batch adds no bindings and no rig changes (`batch-status.ts`,
   `bindings.ts`, runner untouched in the diff) — consistent with §7
   caution 8.
5. Gate housekeeping: `throwaway/b9-reviewB-e2e/` (this lens's drivers)
   must be removed with the other `throwaway/` dirs at the terminal gate.
