# B9 review — Pair B (BLIND), Lens 1: BROWSER THREAT MODEL

**Status**: COMPLETE — **NO-GO** pending F1/F2. 2 blocking findings (SA-refusal
bypass on two ingress paths not in the §2.3 enumeration — the packet §2.3 calls a
sixth path "a blocking finding"), 4 major, 2 minor. All findings reproduced with
executable probes (transcripts below); probe files were scratch-only and are
deleted (TS worktree clean).

**Reviewer**: pair-B lens-1 (browser threat model). **Blindness honored**: no
`b9-reviewA-*` file read (verified — the only design docs opened were
`phase3-playbook.md`, `b9-packets.md`, `typescript-port-plan.md` §4.1/§4.3,
`typescript-port-rulebook.md` §9/§10); the sibling pair-B lens-2 harness
directory `throwaway/b9-reviewB-e2e/` was NOT read either.

**Scope**: TS `main` commits `9fcc489` (B9-R1), `009bad7` (B9-R2), `f6f298b`
(spike docs), `4b1884a` (ARB-A fixes — code only, the resolution doc NOT read);
Python-side notes `B9-R1/R2/D2-SPIKE`/`B9-spike.md` + packet §9 addendum.
Contract arbiters where no Python twin exists: R9.3 (`rulebook:266-270`) and plan
§4.3 / §4.1, cited per finding.

## Hunt list (lens charter) and verdict per item

| # | Hunt item | Verdict |
|---|---|---|
| 1 | Token material reachable by page JS beyond the documented CredentialStore surface | **F3** (token payload in error details); Secret masking otherwise sound (`secret.ts` toString/toJSON/inspect all redact; `serializeTokensPayload` is the single designated reveal site) |
| 2 | localStorage adapter warning adequacy vs actual behavior | **F6** (warning enumerates bearer tokens only; the store also holds the PKCE verifier + CSRF state and the DCR cache; no bulk-clear helper exists for the logout instruction it gives) |
| 3 | State parameter predictability / replay | CLEAN on predictability (32 CSPRNG bytes → 43-char base64url, `redirect-flow.ts:169-173`; probe: `WRYP2lydc1u3scARwuwPL5WikP84uXAsYAWNlYSWek0`, len 43). Replay: single-use delete verified, **F5** on unbounded lifetime |
| 4 | Verifier storage lifetime (cleared after exchange?) | CLEAN — deleted BEFORE the exchange and NOT resurrected on exchange failure (probe C: `pending after failed exchange: null`); **F5** covers the never-cleared parse-failure/abandoned case |
| 5 | Open-redirect vectors in return-URL handling | Return-URL side CLEAN (the exchange uses `pending.redirect_uri` from the store, never the returned URL). Outbound side: **F4** (`beginLogin.redirectUri` unvalidated + undocumented) |
| 6 | SA-secret exposure paths in bundled code (bundle grep) | **F1 + F2** — `accountAuthHeader`'s Basic branch ships in the browser bundle (`/tmp/b9-browser-bundle.js:1294-1299`) and is REACHABLE from the browser package's own public surface on two paths outside the §2.3 enumeration |
| 7 | CSP / postMessage assumptions | CLEAN — the library never navigates, never opens a popup, never uses `postMessage`, and reads no ambient `location` (the caller passes `returnUrl`). No inline-script/eval/wasm dependency in the bundle path. Related: **F7** (secure-context requirement of `crypto.subtle` unstated, non-coded failure) |

## Findings

### F1 — BLOCKING. SA refusal is bypassed on any client derived via `withProject`

`packages/browser/src/client.ts:325-342` installs the §2.3 path-4 gate by
`Proxy`-wrapping ONLY the top-level `MixpanelClient.use`. The core client's
`withProject` (`packages/core/src/client/client.ts:1166-1193`) constructs a
**fresh** `createMixpanelClient(...)` and returns it raw — the Proxy is not
re-applied, so the derived client's `use()` is the ungated core implementation,
which builds a Basic header for `service_account` at `client.ts:1041-1042` via
`accountAuthHeader`.

Probe A (scratch vitest, browser-package imports only):

```
const ws = createBrowserWorkspace({ token, projectId: "1", region: "us", fetch });
await ws.client.use({ account: SA });              // → refused (guard works)
const derived = ws.client.withProject("2");
await derived.use({ account: SA });                // → NO refusal
await derived.me();
// captured header: Authorization: Basic c2EudXNlcjpTVVBFUl9TRUNSRVQ=
```

R9.3 requires service-account Basic auth to be "refused at runtime in browser
builds". It is not, on this path. Note the export guard DOES survive derivation
(`withProject` forwards `fetchImpl`, `client.ts:726` + `:1181`) — only the SA gate
is lost. Neither `sa-refusal.test.ts` (paths 1/2/3/4 only) nor
`throwaway/b9-r1/edges.ts:109-142` probes a derived client.

**Fix**: make `guardClientUse` re-wrap derivations — intercept `withProject` and
return `guardClientUse(target.withProject(...))` (same file, no core edit), and add
a Layer-3 row + an R10.9 edge for the derived path.

### F2 — BLOCKING. The browser entry re-exports the raw `Workspace` constructor, which accepts a service-account session with no refusal and no export guard

`packages/browser/src/index.ts:68` re-exports core `Workspace` (packet §2.5
mandates the re-export). Constructing it directly skips BOTH browser gates:
`createBrowserWorkspace`'s §2.3 path-1 check and `assembleWorkspace`'s
`guardBrowserFetch` (the direct path defaults to `globalThis.fetch`, so
`BROWSER_EXPORT_UNSUPPORTED` never fires either).

Probe G:

```
import { Workspace } from "@mixpanel-headless/browser";
const ws = new Workspace({ session: SA_SESSION, clientOptions: { fetch } });
await ws.client.me();
// captured header: Authorization: Basic c2EudXNlcjpTVVBFUl9TRUNSRVQ=
```

Reachability note (stated honestly): F1 needs an `Account` value and F2 a
`Session` value, and the browser entry exports neither constructor — a consumer
gets them from core `parseAccount`/`parseSession` (a normal sibling dependency in
a published layout, and a common shape in apps that share account-building code
with their server) or by a `as` cast. That does not rescue the requirement: R9.3's
refusal is a runtime property of the browser BUILD, and the bundle grep confirms
the Basic constructor ships unguarded (`base64EncodeUtf8` + `` `Basic ${...}` `` at
bundle lines 1286-1299).

**Fix options** (arbiter call): (a) drop the raw `Workspace` re-export in favour of
the factories, or re-export a browser-gating subclass/wrapper; (b) export an
`assertBrowserSafeSession(session)` guard and call it in the docs' recommended
path; (c) escalate the minimal core seam per the §2.3 row-4 escalation rule
(a `refuseServiceAccount` option on `WorkspaceOptions`). Whatever is chosen,
§2.3's path table and its Layer-3/R10.9 coverage must grow to match.

### F3 — MAJOR. Browser token exchange puts the FULL token payload into `OAuthError.details.response_data`, unredacted

`packages/core/src/auth/oauth-http.ts:242-247` (the §3.1-hoisted
`_post_token_request`, `flow.py:596-605` parity) stringifies the parsed 200 body
into the error details when a required field is missing.

Probe F (browser `completeLogin`, canned IdP returning
`{"access_token":"SECRET_AT","refresh_token":"SECRET_RT"}`):

```
code:    OAUTH_TOKEN_ERROR
details: {"response_data":"{'access_token': 'SECRET_AT', 'refresh_token': 'SECRET_RT'}"}
```

The value never passes through `Secret`, so `JSON.stringify(err.details)` — what
every browser error reporter (Sentry/Bugsnag/`window.onerror` wrappers) does —
exfiltrates live bearer material to a third-party telemetry origin. In node this
was ledgered as **O1**, but that ledger row (b9-packets.md §5.5 row 1) still cites
`flow.ts:898` and scopes the issue to *refresh*-error details; after the B9 hoist
the site is shared and the browser **exchange** path is a new, higher-exposure
consumer that no B9 document assesses.

R10.7 forbids a unilateral TS behavior change (Python twin). **Fix**: (i) re-scope
and re-cite ledger row 1 to `core/src/auth/oauth-http.ts:245` + "shared by node
refresh AND browser exchange"; (ii) add the browser README/JSDoc caveat that
`OAuthError.details` may carry token material and must not be forwarded to
telemetry verbatim; (iii) file the Python-first fix (redact `access_token` /
`refresh_token` keys in `response_data`) into the R10.7 Python-fix queue
(§5.5 row 2) rather than leaving it as a node-only observation.

### F4 — MAJOR. `beginLogin` accepts an arbitrary `redirectUri` with no validation and no "must be a trusted constant" warning

`redirect-flow.ts:86-87, 196-241`: the caller-supplied `redirectUri` is
DCR-registered (`registration.ts:96`) and interpolated into the authorize URL
verbatim. There is no absolute-URL check, no https check, no same-origin default,
and neither the module JSDoc nor `README.md` states that this value must never be
derived from user input. The Python twin has NO equivalent exposure — there the
redirect URI is library-generated (`http://localhost:{port}/callback`,
`flow.py:54`), so this is a browser-only attack surface introduced by B9.

The D2 spike makes it concrete rather than theoretical: it PROVED that Mixpanel
DCR accepts an arbitrary third-party https redirect URI (201 for
`https://spike-b9.example.com/oauth/callback`, packet §9). An app following the
ubiquitous `?returnTo=`/`?next=` pattern therefore hands the authorization code to
the attacker's origin, and the library will happily register that origin first.

**Fix**: document the requirement prominently (README "Redirect URI" section +
`BeginLoginOptions.redirectUri` JSDoc), and consider rejecting non-absolute /
non-https URIs with a coded error (`OAUTH_CONFIG_ERROR`) — a browser-local
adaptation with no Python twin to violate, contract-arbitrated by R9.3.

### F5 — MAJOR. The pending-login record has no TTL: `created_at` is written and never read

`redirect-flow.ts:218-228` writes `created_at`, and `loadPendingRecord`
(`:252-285`) validates only that `state`/`verifier`/`client_id`/`redirect_uri` are
strings — the timestamp is never checked. The record is deleted only on a
SUCCESSFUL parse (`:333-339`); a parse failure (state mismatch, `error=` param,
missing `code`) deliberately leaves it in place (documented), and an abandoned
login leaves it forever.

Probe C: after a state-mismatch `completeLogin`, `pending after mismatch: true`.
With `LocalStorageCredentialStore` that record — CSRF state + PKCE verifier —
survives reloads and browser restarts indefinitely, so a state value that leaked
by any of the usual routes (Referer from the redirect page, browser history,
shared-device localStorage, corporate proxy logs of the redirect URI) remains
redeemable months later in a code-injection/CSRF attempt. OAuth 2.0 security BCP
expects short-lived, single-use state.

**Fix**: add an age gate in `completeLogin` (reuse the already-persisted
`created_at` + the `now` seam; e.g. a documented `maxPendingAgeMs` default with
`BROWSER_NO_PENDING_LOGIN` on expiry) — the field was clearly stored for this — or,
at minimum, document the unbounded lifetime at the class warning and the flow
JSDoc.

### F6 — MINOR. localStorage security warning is narrower than the adapter's actual behavior

`credential-store.ts:109-129` and `README.md:42-50` warn about **bearer tokens**
being XSS-readable and surviving logout, and instruct callers to "call `delete`
for every `CREDENTIAL_KEYS` entry on logout". Two gaps against actual behavior:

1. The store also holds the **PKCE verifier + CSRF state** (`pendingLogin`) and the
   DCR registration (`clientInfo`) — probe E dump shows all three key families.
   Neither is named in the warning; F5 makes the pending record the longest-lived
   of the three.
2. The instruction has no supported helper: `InMemoryCredentialStore` has
   `clear()` (`:104-106`) but `LocalStorageCredentialStore` has none, so a correct
   logout requires the caller to know all three key builders × every region they
   have used. `CREDENTIAL_KEYS` is exported but there is no enumeration helper.

**Fix**: extend the warning text to name all three payload families; add a
`clearAll(regions)` (or `CREDENTIAL_KEYS.all(region)`) helper and reference it from
the logout sentence.

### F7 — MINOR. Secure-context requirement is unstated and fails with a bare `TypeError`

`crypto.subtle` is undefined in insecure contexts (any `http://` origin other than
localhost), while `crypto.getRandomValues` is not — so `beginLogin` gets as far as
the digest and then throws an uncoded error.

Probe H (`crypto.subtle` removed):
`TypeError: Cannot read properties of undefined (reading 'digest')`, `code:
undefined`.

R5 says programs key on codes; this failure has none, and neither
`packages/core/src/auth/pkce.ts` nor the browser README states that the PKCE flow
requires a secure context. **Fix**: guard `challengeFor` with a coded
`OAUTH_CONFIG_ERROR` ("WebCrypto SubtleCrypto unavailable — PKCE requires a secure
context (https or localhost)") and add one README line.

### F8 — MAJOR (correctness/leak). URL fragments are parsed as query text: `returnUrl: location.href` breaks logins and can ship in-page fragment state to the IdP

`parsePastedRedirect` (`core/src/auth/redirect-parse.ts:92-94`) slices at the first
`?` and parses **everything after it**, fragment included — correct for Python
(the localhost callback server hands over `path?query` and the paste grammar never
sees a fragment) but wrong for the browser adaptation, whose own JSDoc example
tells callers to pass `location.href` (`redirect-flow.ts:310-316`).

Probe D — hash-routed SPA, `?code=X&state=S#/route`:
`OAUTH_STATE_MISMATCH` ("does not belong to this login session"). A routine SPA
configuration therefore fails login with a security-flavored error that also masks
genuine CSRF failures.

Probe I — the other param ordering, `?state=S&code=X#session=abc`, is worse: the
fragment is folded into the code and POSTed to the token endpoint —

```
grant_type=authorization_code&code=X%23session%3Dabc&redirect_uri=...&code_verifier=...
```

URL fragments never leave the browser by design; this path exfiltrates whatever the
app keeps there to Mixpanel's token endpoint (and burns the login).

**Fix**: strip at the first `#` in the browser adapter before calling
`parsePastedRedirect` (browser-local; the shared core parser stays byte-identical
for node), or change the documented usage to `location.search`. Add both orderings
as Layer-3 rows.

## Non-blocking observations

- **O1** — `state` comparison is `!==` (non-constant-time, `redirect-parse.ts:117`).
  Not exploitable in a browser (no attacker-observable timing channel on a local
  string compare); noted only so the next reviewer does not re-derive it.
- **O2** — `Secret` masks `toString`/`toJSON`/node inspect, but Chrome DevTools
  renders `#value` for anyone with console access. Inherent to the platform (same
  trust boundary as XSS); no action.
- **O3** — Two concurrent `completeLogin` calls (double-mount React effects, two
  tabs) both read the pending record before either deletes it; both then exchange
  the same code. Not a credential leak (the IdP rejects the second), but the
  single-use property is enforced non-atomically. Worth one sentence in the JSDoc.
- **O4** — `guardBrowserFetch` derives the export origins from the core `ENDPOINTS`
  table as the packet demands, tolerates `Request`/`URL`/string inputs, and
  survives `withProject` derivation (probe B + `client.ts:726`,`:1181`). No bypass
  found.
- **O5** — R10.9 harness spot-check (P3-2(d) item 5): `throwaway/b9-r1/edges.ts`
  reproduces **32 checks / 0 failures** and `throwaway/b9-r2/edges.ts` **35 checks /
  0 failures** at the recorded RUN-record counts. Both reproduce; neither contains a
  derived-client or `Workspace`-direct SA probe (the F1/F2 blind spot).

## Probe inventory (all scratch, deleted; `git status` clean in the TS repo)

| Probe | Question | Result |
|---|---|---|
| A | Is the §2.3 path-4 guard preserved across `withProject`? | NO — Basic header emitted (**F1**) |
| B | Does the export guard survive `withProject`? | YES (O4) |
| C | Pending-record lifetime across parse failure / exchange failure | survives parse failure; deleted after failed exchange (**F5**) |
| D | `location.href` with a hash route | `OAUTH_STATE_MISMATCH` (**F8**) |
| E | What lands in the store after a successful login | tokens (`+00:00`), clientInfo (`Z`), pending cleared |
| F | Error details on a 200-with-missing-fields token response | full token payload in `details.response_data` (**F3**) |
| G | `new Workspace({session: SA})` from the browser entry | Basic header, no refusal, no export guard (**F2**) |
| H | `crypto.subtle` absent (insecure context) | bare `TypeError`, no code (**F7**) |
| I | Fragment with state-first param ordering | fragment POSTed inside `code` (**F8**) |

## Verdict

**NO-GO** until F1 and F2 are resolved (packet §2.3: "The DOUBLED review's
independent duty is to hunt for a sixth path; finding one is a blocking finding" —
two were found, both reproduced). F3/F4/F5/F8 should be resolved or explicitly
dispositioned by the arbiter before the terminal gate, since three of them
(F4/F5/F8) are browser-only surfaces with no Python twin, i.e. exactly the class
the R9.3 contract arbiter exists to cover, and F3 is a stale/underscoped Phase-4
ledger row that the FINAL batch is the last chance to correct.
