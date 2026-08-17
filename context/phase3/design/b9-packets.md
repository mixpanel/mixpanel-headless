# B9 design-lite packets — the browser package (CredentialStore, redirect PKCE over WebCrypto, oauth_token first-class, SA runtime refusal, D2 spike closure) — THE FINAL BATCH

**Status**: v1.0 · 2026-08-16 · P3-6 step 1 output for batch B9 (fable, ≤ high).
Spec of record: `phase3-playbook.md` v1.1 (B9 rows: P3-1 `:105` + `:107` gate
expectation, scope row `:250-256`, P3-3 doubling `:380-387`, P3-6 sharding
`:712-713`) + all recorded discrepancies (#1–#15) + `user-ratifications.md` +
rulebook R9.3/R9.1/R5/R10.8 + plan §4.1 (core/auth PKCE primitives (WebCrypto)),
§4.3 (D2 spike table + the REMAINING UNVERIFIED item + fallback wording), §8
open-question 3. Inbound deferrals: `b8-packets.md` §8 outbound ledger +
`B8-notes.md` "Outbound" (PKCE RFC rows re-translate against WebCrypto; browser
CredentialStore/redirect PKCE/SA refusal with `oauth-constants.ts`
copy-with-cite; B9-gate expectation ALREADY satisfied at B8 — HOLD 3,251/0/0
while adding tests only; Phase-4 burn-in ledger lines; live auth scenarios).

Ground state verified 2026-08-16: Python `ts-port/phase2-contract-support` @
`47bf781` (corpus pin `70c904dc`); TS `main` @ `4095f46` (B8 gate closed:
**3,251 PASS / 0 FAIL / 0 UNPORTED — the full corpus is green**). `packages/browser`
is the Phase-1 skeleton (`src/index.ts` exports `BROWSER_PACKAGE_NAME` only;
`test/` + `tsconfig.json` wired into root vitest/typecheck already). B9 owns
**zero corpus vectors** (P3-1 `:105`; api-map mechanical extraction
`jq '[.workspace_members[]|select(.batch=="B9")]|length'` = **0** — measured
2026-08-16). Verification is therefore: Layer-3 tests (translated where a Python
twin exists, contract-authored from R9.3/plan-4.3 where none does), the R10.9
harness incl. a direct-CPython PKCE differential, the DOUBLED review, and the
D2 spike. **Where browser behavior has no Python twin, the R9.3 / plan-§4.3
contract is the arbiter — every such spec line below carries its citation.**

**Standing rules restated**: NO mutation testing `[SA1]`. R10.13 incremental
protocol on every agent (skeleton first, small frequent edits, notes file).
Python is the behavior arbiter where a twin exists. `analytics` READ-ONLY.
LOCAL COMMITS ONLY, both repos. B9 is fable-tier → bindings would land inline
(P3-2 b′) — but there are NO new bindings (zero vectors, zero api names); the
R10.9 harness still runs per shard. **DOUBLED review** (P3-3): two independent
pairs + arbiter per shard — protocol in §6. **LIVE BUDGET exists for
B9-D2-SPIKE ONLY** (§4): creds check first, ≤2 DCR registration attempts, ≤2
Query-API calls, never suppress stderr, no other live network anywhere in the
batch (all Layer-3/harness traffic goes through canned `fetch` doubles).

## §0 Shard map, dispatch order, and the playbook mapping

### §0.1 Shard table (DISPATCH-ORDER RULE honored: R1 first, R2 second, then D2-SPIKE, then gate)

| Task | Contents | Vectors | Runs |
|---|---|---|---|
| **B9-R1** | Browser package foundation: `CredentialStore` interface (core, plan §4.1) + in-memory default + localStorage adapter with security warning; **the §1 PKCE ruling executed** (core WebCrypto `PkceChallenge` + node migration + B8 suite re-point); `oauth_token` mode wiring over the core client/Workspace; SA Basic-auth runtime refusal on EVERY path (§2.3); Export-API browser exclusion; browser entry points + package exports; browser-bundle smoke promotion (core AND browser) + eslint purity boundary for `packages/browser` | 0 | **FIRST** |
| **B9-R2** | Redirect-based PKCE flow: authorize-URL construction (`_build_authorize_url` twin), state/verifier persistence via `CredentialStore`, redirect-return handling (`_parse_pasted_redirect` semantics), browser DCR twin, token exchange over `fetch` (`exchange_code`/`_post_token_request` twins), login-surface adaptation (`beginLogin`/`completeLogin`); Layer-3 translation of the applicable `test_auth_flow.py` classes + new browser-contract suites | 0 | second (imports R1's store + core PKCE) |
| **B9-D2-SPIKE** | Plan §4.3 open item: browser-origin PKCE end-to-end — DCR redirect-URI acceptance for third-party https origins, live, budgeted (§4); outcome classified + docs wording landed | 0 | third (after R2 exists, so the spike can cite the shipped surface in its docs wording) |
| **B9-GATE** | P3-2 (e) instantiated as the Phase-3 TERMINAL gate: corpus HOLDS 3,251/0/0, smoke (core+browser), differential regression (fresh seed + ALL prior gate seeds), `throwaway/` cleanup, Phase-3 closing duties (§5.4: summary block, playbook status flip, Phase-4 outbound ledger) | 0 | last |

Σ vectors = **0** — matching P3-1 `:105` ("B9 (none — spike-scoped, tests
only)"). No batch-status flip exists for B9 (no owned prefix; the terminal
UNPORTED-probe re-anchor already executed at the B8 flip, `b8-packets.md`
§5.3). The P3-1 `:107` B9-gate expectation (3,179+N = **3,251** with N=72) was
REACHED at B8 and must **HOLD exactly** here.

### §0.2 Mapping vs the playbook P3-6 sketch (recorded, no scope change)

The playbook row (`:712-713`) says: "**B9**: 2 tasks (CredentialStore + PKCE
redirect flow; DCR verification folded into the second)." This packet keeps the
two module shards R1/R2 in dispatch order (rule honored) with two recorded
content re-mappings:

1. **D2-SPIKE is split OUT of task 2** into its own task spec (§4). Reason:
   the spike is the batch's ONLY live-network surface and carries its own hard
   budget, its own cleanup duties, and a docs outcome that both R2 and the gate
   consume; folding it into R2 would put live calls inside a module task whose
   R10.9 harness must be entirely canned (LIVE-BUDGET rule above), and a
   killed/retried R2 agent would risk double-spending the DCR budget. The
   spike is still "DCR verification [of] the second [task's flow]" — same
   content, separate dispatch, sequenced after R2.
2. **The §1 PKCE-placement ruling adds node-migration work to R1** that the
   sketch did not name: `packages/node/src/auth/pkce.ts` (B8's node-crypto
   impl) is REPLACED by a re-export of the new core WebCrypto implementation,
   with the B8 test suite re-pointed (§1.3). This follows the `b8-packets.md`
   §4.1 row-1 note ("B9 builds its OWN WebCrypto async twin — do not
   pre-abstract") whose §8 outbound row explicitly hands B9 the placement
   decision, and R10.8 (shared internals ported once, by name) decides it.

Dispatch is strictly sequential R1 → R2 → D2-SPIKE → GATE (R2 imports R1's
`CredentialStore` + the §1 core `PkceChallenge`; no shared-file merge points —
R1 owns `credential-store.ts`/`client.ts`/`errors.ts`/`index.ts`, R2 owns
`redirect-flow.ts`/`registration.ts` and APPENDS its exports to `index.ts`
after R1 lands).

### §0.3 Core touches (enumerated and closed: two in R1, one hoist family in R2)

1. **`packages/core/src/auth/pkce.ts` — NEW (the §1 ruling).** WebCrypto PKCE
   primitives belong in core per plan §4.1 ("src/auth/ … PKCE primitives
   (WebCrypto)"). R9.1-legal: core may touch the `crypto` global ("no globals
   beyond `fetch`/`crypto`/`TextEncoder`"). Pure of `node:*`; the browser
   smoke bundles it.
2. **`packages/core/src/auth/credential-store.ts` — NEW (interface only).**
   Plan §4.1: "`core` defines `TokenResolver` / `CredentialStore` interfaces;
   `node` and `browser` provide implementations." Types + JSDoc only, zero
   runtime code beyond an exported `const` key-name table (§2.1). No existing
   core signature changes. (`TokenResolver` already exists,
   `core/src/auth/account.ts:74` — untouched.)

3. **R2's fetch-pure OAuth hoist family** (§3.1 — the second R10.8 ruling of
   this packet): the fetch-only, `node:*`-free halves of the B8 flow/DCR
   modules (`buildAuthorizeUrl`, `postTokenRequest`, `parsePastedRedirect`
   + its `parseQs` dependency, the DCR POST half, and the
   `OAUTH_BASE_URLS`/default-scope constants) MOVE from `packages/node` into
   `packages/core/src/auth/`, with node re-pointing by import (its B8 Layer-3
   suites stay green UNCHANGED — that is the zero-behavior-change proof) and
   browser importing the same names. Supersedes the B8 outbound
   "copy-with-cite" instruction — recorded in §3.1 with rationale.

Node touches (R1, part of the §1 migration): `packages/node/src/auth/pkce.ts`
(becomes re-export), `packages/node/src/auth/flow.ts:494` (`await` the now-async
`generate()`), `packages/node/test/pkce.test.ts` (re-point + async-adapt,
assertions UNWEAKENED — §1.3). Node touches (R2): the §3.1 re-points only.
Nothing else in `packages/node` moves.

### §0.4 R9 posture for `packages/browser`

- `packages/browser` gets the SAME eslint purity boundary as core
  (`eslint.config.js:47-75` block extended to
  `files: ["packages/core/**/*.ts", "packages/browser/**/*.ts"]`): no `node:*`
  / `fs` / `path` / `os` / `undici` imports, no `process` global. Browser code
  may additionally touch `localStorage`/`globalThis` storage objects — only in
  the localStorage ADAPTER file, and only via an injected `Storage`-shaped
  parameter (default `globalThis.localStorage`), so the module graph stays
  jsdom-free and testable under plain vitest/node.
- `packages/browser` imports core via the repo's relative-path precedent
  (`../../core/src/…js`, the `b8-packets.md` §0.4 pattern). It may NOT import
  `packages/node` (node is `node:*`-infested by design); the two OAuth
  constants it shares with node are copied WITH CITE per the B8 outbound row —
  §3.2 pins the values.
- No env reading anywhere in browser (R9.4: env is node-only). All
  configuration arrives as constructor/function input.
- Root `npm run test` / `npm run typecheck --workspaces` already pick up
  `packages/browser` (workspace glob + existing `tsconfig.json`); R1 adds real
  `exports` to `packages/browser/package.json` (currently script-only).

## §1 The PKCE-placement ruling (WebCrypto in core; node migrates)

**RULING: one WebCrypto implementation in `packages/core/src/auth/pkce.ts`,
reused by BOTH node and browser. The B8 node-crypto `pkce.ts` is retired to a
re-export in the same commit (B9-R1).**

### §1.1 Analysis

The `b8-packets.md` §4.1 row-1 placement note deferred this ("B9 builds its
OWN WebCrypto async twin — do not pre-abstract") and the §8 outbound row hands
the decision here. Options considered:

- **(a) Keep node's `node:crypto` impl + add a second WebCrypto impl in
  browser.** Rejected: two hand-maintained implementations of the same RFC 7636
  semantics is the exact R10.8 founding failure mode ("shared internals once,
  first"); rulebook §8-adjacent per-se finding ("writing a new local helper
  whose body reproduces either semantics is a per-se review finding regardless
  of behavioral equivalence"). The B8 note was a B8-SCOPED sequencing
  instruction (don't build browser plumbing inside the node batch), not a
  standing architecture decision — its own outbound row says the B9 packet
  rules.
- **(b) WebCrypto impl in `packages/browser` only.** Rejected: plan §4.1
  places "PKCE primitives (WebCrypto)" in `core/src/auth/` explicitly, and a
  browser-homed impl would leave node on `node:crypto` (option (a)'s dual-impl
  problem) or force node→browser imports (no such edge exists in the topology).
- **(c) WebCrypto impl in core; node re-exports; browser imports.** ACCEPTED.
  Node ≥20 has WebCrypto globally (`globalThis.crypto.subtle` /
  `getRandomValues` — root `package.json` `engines.node: ">=20"` already pins
  this); R9.1 explicitly allows core to touch the `crypto` global; the browser
  smoke then proves bundle-purity of the single impl for free.

Sync→async consequence: `crypto.subtle.digest` is Promise-returning, so
`challengeFor` and `generate` become **async**. Sole existing consumer is
`packages/node/src/auth/flow.ts:494` (`const pkce = PkceChallenge.generate();`)
inside the already-`async login()` — the migration is one `await`. Python's
sync `generate()` (`pkce.py:47-73`) has no observable-ordering contract around
it (generation happens before any I/O in `login`, `flow.py:270` region), so
asyncification is behavior-preserving at every observation point.

### §1.2 The core implementation spec (B9-R1)

`packages/core/src/auth/pkce.ts` — port of `_internal/auth/pkce.py:1-73`
(whole file), Python is the behavior arbiter:

```ts
export class PkceChallenge {
  readonly verifier: string;   // 86-char base64url, no padding
  readonly challenge: string;  // 43-char base64url(SHA-256(ASCII verifier)), no padding
  constructor(fields: { readonly verifier: string; readonly challenge: string });
    // Object.freeze(this) — frozen-dataclass twin (same as the B8 class)
  static async generate(): Promise<PkceChallenge>;
    // 64 bytes via crypto.getRandomValues(new Uint8Array(64))  [secrets.token_bytes(64), pkce.py:65]
    // verifier = base64url(bytes), '=' stripped                 [pkce.py:66]
  static async challengeFor(verifier: string): Promise<string>;
    // base64url(await crypto.subtle.digest("SHA-256", asciiBytes(verifier))), '=' stripped
    // [pkce.py:68-71; RFC 7636 §4.2 S256]
}
```

Implementation constraints:

- **No `Buffer`** (core purity): base64url encoding of a `Uint8Array` is a
  small pure helper in the same file (btoa-free table walk or
  `String.fromCharCode` + `btoa`-equivalent — builder's choice, but it must
  handle arbitrary bytes, strip `=` padding, and use the `-`/`_` alphabet;
  lock with the RFC vector + a fixed-bytes golden). Note core's existing
  `base64EncodeUtf8` (`account.ts:537`) is TEXT→base64 (standard alphabet) —
  NOT reusable for bytes→base64url; do not bend it (watchlist: a wrong-alphabet
  encode still yields 86/43-char strings — length checks alone cannot catch
  it, the RFC Appendix-B vector does).
- ASCII encode of the verifier via `TextEncoder` (verifier is base64url
  alphabet ⊂ ASCII, so UTF-8 == ASCII here; matches `verifier.encode("ascii")`,
  `pkce.py:68`).
- JSDoc R1.3 on everything; cite `pkce.py` line ranges.

### §1.3 The node migration spec (B9-R1, same commit — zero behavior change, PROVEN)

1. `packages/node/src/auth/pkce.ts` → delete the `node:crypto` implementation;
   the file becomes a documented re-export:
   `export { PkceChallenge } from "../../../core/src/auth/pkce.js";` with a
   header citing this ruling (§1) + R10.8. (Keeping the file preserves every
   existing import path — `flow.ts:76` is untouched except for the await.)
2. `packages/node/src/auth/flow.ts:494`:
   `const pkce = await PkceChallenge.generate();` — the only call-site edit.
3. `packages/node/test/pkce.test.ts` re-pointed at the SAME import path (now
   transparently core) and async-adapted (`await` on `generate`/
   `challengeFor`). **R10.2: every one of the 10 existing assertions survives
   verbatim** — the 9 translated `TestPkceChallenge` rows (86-char verifier
   lock, base64url-no-pad alphabet for verifier AND challenge, challenge =
   SHA-256 of verifier, determinism of `challengeFor`, per-generation
   uniqueness ×2, 43-char challenge lock, string types) + the RFC 7636
   Appendix-B vector row (`challengeFor("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
   === "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"`, `pkce.test.ts:92-97`).
   These are the "zero behavior change" proof demanded by the dispatch: the
   RFC vector pins the hash+encoding path bit-exactly and the 86-char lock
   pins the entropy width; nothing else about the class is observable.
4. The browser package does NOT get its own suite copy of the full 10 —
   `packages/browser/test/pkce-webcrypto.test.ts` (R2, §3.5) re-runs the RFC
   Appendix-B vector + the 86/43 locks THROUGH THE BROWSER ENTRY POINT
   (import via `packages/browser/src/index.ts`) to lock the re-export chain,
   per the B8 outbound row "PKCE RFC 7636 vector rows re-translate against
   WebCrypto"; the exhaustive suite lives once, at the core-owned node path
   (single-implementation ⇒ single exhaustive lock, R10.8).

## §2 Shard B9-R1 — browser package foundation

Model **fable**, effort ≤ high, R10.13 protocol, notes file
`context/phase3/notes/B9-R1-notes.md`. No live network. Contract arbiter:
R9.3 + plan §4.3 tier table (cited per item below); Python arbiter only where
a twin is named.

### §2.1 `CredentialStore` — interface in core, implementations in browser

**Interface** (`packages/core/src/auth/credential-store.ts`, §0.3 touch 2;
plan §4.1 is the placement authority). No Python twin — the contract is R9.3
("injectable `CredentialStore`") + what R2's flow and the token wiring need.
PASTED CONTRACT (R10.10 — this IS the signature the consumers compile
against):

```ts
/** String-keyed credential persistence seam (R9.3). Keys are namespaced by
 *  the library (see CREDENTIAL_KEYS); values are opaque serialized strings.
 *  All methods may be sync or async on the implementor side — consumers
 *  always `await` (Promise<...> | direct value both satisfy the types). */
export interface CredentialStore {
  get(key: string): Promise<string | null> | string | null;
  set(key: string, value: string): Promise<void> | void;
  delete(key: string): Promise<void> | void;
}

/** Key-name table (exported const; single source of the namespace). */
export const CREDENTIAL_KEYS = {
  tokens:       (region: string) => `mp.tokens.${region}`,
  clientInfo:   (region: string) => `mp.oauth_client.${region}`,
  pendingLogin: (region: string) => `mp.pending_login.${region}`,
} as const;
```

Design notes (binding on the builder):
- `get` returns `null` for absent (never `undefined` — R3.9 optionality rules
  favor an explicit null contract at seams; mirrors `storage.load_client_info`
  returning `None`, `client_registration.py:92-93` cache-check shape).
- Per-REGION keying mirrors Python's on-disk layout
  (`~/.mp/oauth/client_{region}.json`, tokens per account/region — CLAUDE.md
  config table); browser has no account axis in v1 (oauth_token + PKCE only),
  so region is the whole scope. Record this as a documented narrowing in the
  module header (no Python twin to weaken — R9.3 arbiter).
- Value payloads are JSON text. Datetime fields inside them follow **R11.9**
  (the amendment explicitly binds "B9's browser CredentialStore"): every
  WRITER renders datetimes through the Python-twin formatter — tokens payload
  = `tokens.json` twin ⇒ `datetime.isoformat()` shape `+00:00` via core
  `pythonUtcIsoformat` (`core/src/auth/token.ts:87` — already core-homed, no
  node import needed); client-info payload = `client_{region}.json` twin ⇒
  pydantic-JSON `Z` shape. READ paths re-use core `parseOAuthTokens`
  (`token.ts:331`) / `parseOAuthClientInfo` (`token.ts:392`) — strict,
  mirroring `_read_browser_tokens`'s strict posture per R11.9's "mirror
  per-path, never blanket-lax" (the browser store only ever reads its own
  writes; a round-trip lock test makes that closed loop explicit). NO copy of
  `packages/node/src/auth/pydantic-datetime.ts` into browser — if the builder
  finds a genuinely lax-twin read path, STOP and escalate rather than
  duplicating the helper (R10.8).

**Implementations** (`packages/browser/src/credential-store.ts`):
- `InMemoryCredentialStore` — the DEFAULT (R9.3 "default in-memory"): a
  `Map<string, string>`; `clear()` convenience allowed as an extra.
- `LocalStorageCredentialStore` — the documented adapter (R9.3 "documented
  localStorage adapter with security warning"). Constructor
  `new LocalStorageCredentialStore(storage?: StorageLike)` where `StorageLike`
  = `{getItem, setItem, removeItem}` structural type, default
  `globalThis.localStorage` (throws a coded `OAuthError`
  (`OAUTH_CONFIG_ERROR`) if absent — running under node without injection).
  **The security warning is a REQUIREMENT, not a nicety**: module + class
  JSDoc must state that localStorage is synchronous, origin-scoped,
  XSS-readable, and survives logout unless `delete`d; that bearer tokens in
  localStorage are readable by any script on the origin; and that the
  in-memory default is the recommended posture with re-login on reload. The
  review pairs verify the warning text exists and says these things (§6
  checklist item R1-4).

### §2.2 `oauth_token` mode wiring — first-class (R9.3, D2 Tier C)

`packages/browser/src/client.ts`:

```ts
export interface BrowserSessionOptions {
  readonly token: string;                    // bearer (server-minted or PKCE-obtained)
  readonly projectId: string;                // digit string (core ProjectId)
  readonly region: "us" | "eu" | "in";
  readonly workspaceId?: number;
  readonly accountName?: string;             // default "browser"
}
export function browserSession(options: BrowserSessionOptions): Session;
export interface BrowserWorkspaceOptions {
  readonly session?: Session;                // pre-built (must be non-SA — §2.3)
  readonly store?: CredentialStore;          // default new InMemoryCredentialStore()
  readonly fetch?: typeof fetch;             // R2.4 seam, default globalThis.fetch
  readonly clientOptions?: Omit<MixpanelClientOptions, "session">;
}
export function createBrowserWorkspace(
  options: BrowserSessionOptions & BrowserWorkspaceOptions,
): Workspace;   // core Workspace — the real facade, not a wrapper class
```

- `browserSession` builds the `oauth_token`-type `Account` through core
  `parseAccount` (`account.ts:434`) and the `Session` through core
  `parseSession` (`session.ts:329`) — binding-honesty analogue: NEVER
  hand-assemble the discriminated union or auth headers in browser code
  (P3-5 rule 3 spirit; `accountAuthHeader`/`sessionAuthHeader` stay the only
  header builders).
- `createBrowserWorkspace` = §2.3 SA gate → §2.4 export-refusing fetch wrap →
  core `new Workspace({session, client: undefined, clientOptions})`
  (`workspace.ts:1167` + `WorkspaceOptions` `:496`). Resolver-path
  construction (account/project/target axes) is NOT exposed in browser v1 —
  no env, no config, no bridge exist there (R9.4); the only axes are the
  explicit options above. Document as a narrowing with R9.4 cite.
- When PKCE (R2) has persisted tokens, `createBrowserWorkspaceFromStore(
  {region, projectId, store, …})` reads `CREDENTIAL_KEYS.tokens(region)`,
  parses via `parseOAuthTokens`, refuses expired-with-no-refresh with the
  Python-coded `OAUTH_TOKEN_ERROR`, and constructs the same way. (Refresh in
  browser: OUT of v1 scope unless the D2 spike lands ACCEPTED — record
  disposition in R1 notes; the refresh-token grant twin is `flow.py:442-498`
  and would be an R2 follow-on, not silently added here.)

### §2.3 Service-account Basic-auth runtime refusal — EVERY path (R9.3)

New error module `packages/browser/src/errors.ts`:

```ts
export class BrowserUnsupportedError extends MixpanelHeadlessError { ... }
export const BROWSER_SERVICE_ACCOUNT_REFUSED = "BROWSER_SERVICE_ACCOUNT_REFUSED";
export const BROWSER_EXPORT_UNSUPPORTED = "BROWSER_EXPORT_UNSUPPORTED";
```

Codes are browser-local constants, NOT added to `errors-codes.gen.ts` (that
file is generated from the Python contract artifact and hand-edit-tripwired —
`scripts/gen-error-codes.mjs`; these codes have no Python twin by
construction). R5: assertions and docs key on the CODE, never message text.
The message must be explanatory per R9.3: name the account type received, say
WHY (Basic credentials are long-lived secrets that must not ship to a
browser origin — policy holds even though CORS would technically permit it,
plan §4.3 Tier C note), and point at `oauth_token` / PKCE as the supported
modes.

**Enumerated refusal paths — each is a distinct runtime gate + a distinct
Layer-3 test; the R10.9 harness probes all of them (§2.7):**

| # | Path | Gate location |
|---|---|---|
| 1 | `createBrowserWorkspace({session})` with `session.account.type === "service_account"` | first statement of the factory, before any client construction |
| 2 | `browserSession(...)` cannot even EXPRESS SA (options carry only `token`) — compile-time exclusion; test asserts the runtime gate anyway via path 1 (defense in depth) | type-level + path-1 gate |
| 3 | `createBrowserWorkspaceFromStore(...)` when the store yields a persisted record whose parsed account is SA (someone wrote SA creds into localStorage out-of-band) | immediately after parse, before header/token use |
| 4 | `Workspace.use(account=…)` / session switching on a browser-built facade: the browser factory passes NO `sources` (§2.2), so core `use()`'s re-resolution cannot fetch a config SA — but `use()` accepts an explicit in-memory replacement path; gate = a browser-installed guard wrapping the facade's session replacement (builder locates the single core seam — `sessionReplace` consumers / `WorkspaceOptions` — and installs the check WITHOUT modifying core: if no injection point exists without a core edit, STOP and escalate to the arbiter with the minimal-seam proposal rather than silently patching core) | wrapper seam; escalation rule inline |
| 5 | Direct misuse of R2's flow with an SA session (e.g. `beginLogin` given a store carrying SA material) — R2 functions take no Account at all (state/verifier/client-info only), so this is compile-time excluded; documented in R2's header | type-level |

Rows 2 and 5 are the "enumerate every path incl. resolve/session construction"
demand from the dispatch: browser exposes NO resolver-path construction
(R9.4, §2.2), so construction-time SA ingress reduces to rows 1 and 3, plus
the switching row 4. The DOUBLED review's independent duty (§6) is to hunt
for a sixth path; finding one is a blocking finding.

### §2.4 Export-API exclusion (plan §4.3: Export is Node-only)

The D2 spike table: `data.mixpanel.com` / `data-eu…` serve NO CORS headers —
browser calls are dead on arrival. The browser factory returns the full core
`Workspace` (R10.8 forbids a forked facade), so exclusion is enforced at the
TRANSPORT: `createBrowserWorkspace` wraps the injected/global `fetch` with a
guard that rejects any request whose URL origin equals the origin of ANY
region's `"export"` endpoint in the core `ENDPOINTS` table
(`client/url.ts:31` — derive the origin set from the imported table at wrap
time; never restate the `data.mixpanel.com`/`data-eu…`/`data-in…` literals)
by THROWING `BrowserUnsupportedError`
(`BROWSER_EXPORT_UNSUPPORTED`) synchronously-in-promise BEFORE any network
attempt. `streamEvents`/`streamProfiles`/`api`-escape-hatch export paths thus
fail fast with one coded, documented error instead of an opaque CORS
`TypeError`. Docs: browser README lists export streaming under "Node-only"
with the plan §4.3 cite. Layer-3: canned-fetch test proving (a) Query-host and
App-host requests pass through untouched, (b) each export host is refused
with the code, (c) the wrapped fetch preserves the R2.4 injection (the guard
wraps whatever fetch the caller injected).

### §2.5 Entry points, package exports, bundle promotion

- `packages/browser/src/index.ts` (replaces the skeleton): exports
  `BROWSER_PACKAGE_NAME` (kept — the skeleton smoke test references it),
  `InMemoryCredentialStore`, `LocalStorageCredentialStore`,
  `browserSession`, `createBrowserWorkspace`, `createBrowserWorkspaceFromStore`,
  `BrowserUnsupportedError` + both codes, and RE-exports the core surface a
  browser consumer needs (`Workspace`, `Session`, `PkceChallenge`,
  `CredentialStore` type, `CREDENTIAL_KEYS`, the error hierarchy) — one
  entry point, R7-consistent.
- `packages/browser/package.json`: add `"exports": {".": "./src/index.ts"}`
  form consistent with `packages/core`/`packages/node` current shape (match
  whatever field set they use — inspect, don't invent; version/private flags
  unchanged).
- **Smoke promotion** (`scripts/browser-smoke.mjs`): `entryPoints` grows to
  `["packages/core/src/index.ts", "packages/browser/src/index.ts"]` (one
  build call, two entries — esbuild fails the whole build if EITHER pulls
  `node:*`; keep the log line listing both). This makes `packages/browser` a
  REAL browser build target in `npm run check`, per the ground-state demand.
- **ESLint boundary** extension per §0.4.

### §2.6 Layer-3 (R1)

No Python-twin test files exist for the store/refusal surface (new code, R9.3
arbiter — every suite header cites R9.3/plan §4.3 instead of a Python file,
the phase2-audit A2 header style):

| Suite | Locks |
|---|---|
| `packages/browser/test/credential-store.test.ts` | ONE shared contract suite (a `describe.each` over both implementations): get-absent→null, set/get round-trip, delete, overwrite, key isolation, non-ASCII values (`"𝒳"`), empty-string value; localStorage adapter additionally: injected `StorageLike` used (no global touch), missing-global coded throw, security-warning JSDoc EXISTS (a source-text grep test is acceptable and precedented by the repo's header-grep checks) |
| `packages/browser/test/token-serialization.test.ts` | R11.9 writer shapes: tokens payload `expires_at` renders `+00:00` (never `Z`) via `pythonUtcIsoformat`; client-info `created_at` renders the pydantic-JSON `Z` shape; strict-read round-trip through `parseOAuthTokens`/`parseOAuthClientInfo`; byte-parity golden copied-with-cite from the B8 goldens (`b8-reviewB-resolution.md` probe table) |
| `packages/browser/test/sa-refusal.test.ts` | §2.3 rows 1, 3, 4 each throw `BROWSER_SERVICE_ACCOUNT_REFUSED` (code assert, R5); rows 2/5 documented as type-level (compile-error fixtures via `// @ts-expect-error`) |
| `packages/browser/test/oauth-token-mode.test.ts` | `browserSession` → real `parseAccount`/`parseSession` output (field spellings per R7.6); canned-fetch `createBrowserWorkspace` issues a Query-host call carrying `Authorization: Bearer <token>` built by the CORE header path (spy on fetch, assert header byte-exact); workspace-scoped path when `workspaceId` set (`maybe_scoped_path` behavior via the core client — no re-implementation) |
| `packages/browser/test/export-refusal.test.ts` | §2.4 (a)/(b)/(c) |
| `packages/node/test/pkce.test.ts` (re-point) | §1.3 — all 10 assertions, async-adapted, unweakened |

### §2.7 R10.9 throwaway harness (R1) — `throwaway/b9-r1/`

No oracle families exist for this surface (zero registry apis) — per the P3-2
(c) wire-precedent, the harness reduces to the mandatory edge set + hand-built
probes + one direct-CPython differential, all recorded in a RUN.md (counts,
seeds, divergence table) appended to `B9-R1-notes.md`:

1. **Mandatory edge set** through the store contract: integral-float-string
   value `"18.0"`, fractional `"1.5"`, `"true"`, empty string, empty-key
   guard, non-BMP `"𝒳"` key AND value, plus **every error branch**:
   `BROWSER_SERVICE_ACCOUNT_REFUSED` ×(paths 1,3,4), `BROWSER_EXPORT_UNSUPPORTED`
   ×3 hosts, localStorage-missing `OAUTH_CONFIG_ERROR`, expired-no-refresh
   `OAUTH_TOKEN_ERROR`, malformed-persisted-tokens parse rejection.
2. **CredentialStore contract fuzz**: fast-check, ≥500 examples (P2-9 budget
   analogue), random key/value strings (unicode-biased) through a
   set/get/delete/overwrite command sequence against BOTH implementations,
   asserting observational equivalence between them (the in-memory store is
   the model, the localStorage adapter over an in-test StorageLike is the
   SUT).
3. **PKCE differential vs live CPython** (the module's one cross-language
   surface): ≥500 random verifiers (base64url alphabet, lengths 43–128 per
   RFC range, plus the 86-char production shape) — TS
   `await PkceChallenge.challengeFor(v)` vs
   `uv run python -c` `hashlib.sha256(v.encode('ascii'))` base64url-stripped
   (batched: ONE python process reading a JSON list on stdin — the
   hook-blocked spellings do not arise; never bare `python`). Zero
   divergences or the task blocks. Seed + count in the RUN record.

### §2.8 R10.10 consumers (R1)

- **B9-R2** consumes: `CredentialStore` + `CREDENTIAL_KEYS` (pending-login
  state, tokens, client-info persistence), core `PkceChallenge` (§1.2
  signature), `BrowserUnsupportedError` pattern for its own coded errors.
- **`packages/node/src/auth/flow.ts:494`** consumes core
  `PkceChallenge.generate()` (now awaited) — signature pasted at §1.2.
- **End users** consume §2.2's pasted signatures — they ARE the contract
  (api-map has zero B9 rows; this packet is the signature registry for the
  batch; the gate copies them into the Phase-3 summary block).

### §2.9 Done-criteria (R1)

Files on disk + `tsc --strict` clean (workspace typecheck incl. browser) +
§2.6 suites green + §1.3 node suite green post-migration + `npm run check`
green (incl. the PROMOTED two-entry smoke) + R10.9 RUN record in the notes +
one TS commit (core pkce + node migration + browser foundation land
TOGETHER — the migration must never straddle commits with two live
implementations). No Python-repo change in R1 (notes/packet commits excepted).

## §3 Shard B9-R2 — redirect-based PKCE flow + login surface

Model **fable**, effort ≤ high, R10.13 protocol, notes file
`context/phase3/notes/B9-R2-notes.md`. No live network (D2-SPIKE owns the
only live budget). Python arbiter: `flow.py` / `client_registration.py` for
every twinned behavior; R9.3/plan §4.3 for the redirect-shape adaptation.

### §3.1 The fetch-pure hoist (core touch 3; second R10.8 ruling)

The B8 node modules already CONTAIN correct, doubly-reviewed, Layer-3-locked
ports of everything the browser flow needs except the redirect adaptation
itself. Duplicating them in browser ("copy-with-cite", the B8 outbound row's
assumption) would create second implementations of `flow.py:395-635` +
`client_registration.py:96-170` semantics in the one area with NO second
oracle — the R10.8 failure mode. RULING: hoist the fetch-pure halves to core;
node re-points; browser imports. The B8 outbound copy-with-cite instruction is
SUPERSEDED for these names (it assumed no core hoist; with one, both packages
import by name and nothing is duplicated — only the two constants were ever
copy-candidates anyway).

| Hoisted name (module-level function/const) | From (B8 home) | To (core) | Node after |
|---|---|---|---|
| `OAUTH_BASE_URLS` (us/eu/in, trailing slash — `client_registration.py:39-44`) + the DCR default-scope constant (`_DEFAULT_SCOPE`, `client_registration.py:48-53`) | `packages/node/src/auth/oauth-constants.ts` (+ scope's current TS home — locate by grep) | `packages/core/src/auth/oauth-constants.ts` | re-export |
| `parseQs` (`parse_qs` twin) | `packages/node/src/auth/query-params.ts` | `packages/core/src/auth/query-params.ts` | re-export |
| `parsePastedRedirect` (`_parse_pasted_redirect`, `flow.py:51-117`) | `packages/node/src/auth/flow.ts:199` | `packages/core/src/auth/redirect-parse.ts` | re-export |
| `buildAuthorizeUrl` (`_build_authorize_url`, `flow.py:606-635`) — currently the PRIVATE `OAuthFlow.#buildAuthorizeUrl` (`flow.ts:703`); extraction lifts it to a module-level pure function `buildAuthorizeUrl(baseUrl, {clientId, redirectUri, challenge, state})`; the class method body becomes a one-line delegate | `packages/node/src/auth/flow.ts:703` | `packages/core/src/auth/oauth-http.ts` | delegate |
| `postTokenRequest` (`_post_token_request`, `flow.py:500-605`) — currently `OAuthFlow.#postTokenRequest` (`flow.ts:778`); lifts to `postTokenRequest(fetchImpl, baseUrl, formData, {operation, errorCode, accountName?})`; class delegates | `packages/node/src/auth/flow.ts:778` | `packages/core/src/auth/oauth-http.ts` | delegate |
| DCR POST half (`client_registration.py:96-170`: region gate `:97-103`, register-URL build `:104`, body `:106-112`, network-error branch `:114-121`, 429 branch `:123-132`, non-success branch `:134-144`, JSON/`client_id` parse `:146-157`, `OAuthClientInfo` assembly with injected `now` `:159-165`; the `storage.save_client_info` cache write `:168` stays OUTSIDE the hoist (node keeps `OAuthStorage`, browser uses `CredentialStore`)) as `registerClient(fetchImpl, region, redirectUri, {now?})` — node's `ensureClientRegistered` keeps its cache wrapper and delegates the POST | `packages/node/src/auth/client-registration.ts` | `packages/core/src/auth/oauth-http.ts` | delegate |

Constraints: hoisted code must already be `node:*`-free (it is — fetch +
core imports only; the `node:*` imports in `flow.ts:42-45` serve
login/port/paste surfaces that STAY in node). The moved lines keep their
`flow.py`/`client_registration.py` citations. **Zero-behavior-change proof =
the untouched B8 suites** (`oauth-flow-login.test.ts`,
`oauth-flow-refresh.test.ts`, `client-registration.test.ts`,
`settings-headers` unaffected) all green after the re-point, plus the browser
smoke proving the hoisted modules bundle clean. **STOP-condition**: if
extraction of any row turns out non-mechanical (hidden coupling to
storage/narration state beyond parameters), STOP, keep that row node-homed,
and escalate to the arbiter with a minimal-seam proposal — do NOT write a
browser duplicate without an arbiter-blessed disclosure.

### §3.2 The redirect flow (`packages/browser/src/redirect-flow.ts`)

Browser adaptation of `OAuthFlow.login` (`flow.py:227-393`): the redirect
LEAVES the page, so login splits into begin/complete. No callback server, no
paste fallback, no `webbrowser` — the Python steps map as follows (document
this table in the module header):

| Python `login()` step | Browser twin |
|---|---|
| PKCE + state generation (`flow.py:268-270`: `PkceChallenge.generate()`, `state = secrets.token_urlsafe(32)`) | `await PkceChallenge.generate()` (core §1.2) + `state` = 32 random bytes via `crypto.getRandomValues`, base64url-no-pad (43 chars — same alphabet/length as `token_urlsafe(32)`) |
| port probe + `redirect_uri = http://localhost:{port}/callback` | caller-supplied `redirectUri` (the app's own https URL) — REQUIRED option, no default |
| DCR `ensure_client_registered` | browser `ensureBrowserClientRegistered` = core `registerClient` + `CredentialStore` caching under `CREDENTIAL_KEYS.clientInfo(region)` (cache-hit rule identical to Python: cached client returned only when `redirect_uri` matches — `client_registration.py:92-93`) |
| `_build_authorize_url` | core `buildAuthorizeUrl` (§3.1) — byte-identical output |
| callback wait / paste race | `handleRedirect(returnUrl)` on the return page |
| `exchange_code` | `exchangeCode` via core `postTokenRequest` with the verbatim form fields |
| persist via `OAuthStorage` when `persist=True` | ALWAYS persists via the injected `CredentialStore` (in-memory default = no durable persistence unless the caller opts into the localStorage adapter — R9.3 posture) |

PASTED SIGNATURES (R10.10):

```ts
export interface BeginLoginOptions {
  readonly region: "us" | "eu" | "in";   // validated against OAUTH_BASE_URLS keys;
                                         // unknown → OAuthError OAUTH_CONFIG_ERROR
                                         // (flow.py:164 twin — same code)
  readonly redirectUri: string;          // the app's return URL, registered via DCR
  readonly store: CredentialStore;
  readonly fetch?: typeof fetch;
  readonly now?: () => number;           // clock seam (client-info created_at, token expires_at)
}
export interface BeginLoginResult {
  readonly authorizeUrl: string;  // caller navigates (location.assign) — the library NEVER navigates
  readonly state: string;
}
export async function beginLogin(options: BeginLoginOptions): Promise<BeginLoginResult>;
  // 1. region gate  2. DCR (cached)  3. PKCE + state  4. persist pending record
  // under CREDENTIAL_KEYS.pendingLogin(region)  5. return buildAuthorizeUrl(...)

export interface CompleteLoginOptions {
  readonly region: "us" | "eu" | "in";
  readonly returnUrl: string;            // full URL or query string — parsePastedRedirect grammar
  readonly store: CredentialStore;
  readonly fetch?: typeof fetch;
  readonly now?: () => number;
}
export async function completeLogin(options: CompleteLoginOptions): Promise<OAuthTokens>;
  // 1. load pending record — ABSENT → BrowserUnsupportedError-family coded
  //    error BROWSER_NO_PENDING_LOGIN (no Python twin: Python holds state
  //    in-process; R9.3 arbiter — this is the replay/expired-tab branch)
  // 2. parsePastedRedirect(returnUrl, {expectedState}) — Python codes verbatim:
  //    OAUTH_PASTE_ERROR (empty/malformed/missing code+state, flow.py:86,105-106),
  //    OAUTH_AUTH_DENIED (error param, :98 — error_description appended when present),
  //    OAUTH_STATE_MISMATCH (:113)
  // 3. DELETE the pending record BEFORE the exchange (single-use state — a
  //    second completeLogin with the same URL hits branch 1; replay-attack lock)
  // 4. exchange: postTokenRequest(fetch, base, {grant_type:"authorization_code",
  //    code, redirect_uri, client_id, code_verifier}, {operation:"Token exchange",
  //    errorCode:"OAUTH_TOKEN_ERROR"})   [flow.py:428-434 field-for-field]
  // 5. persist tokens under CREDENTIAL_KEYS.tokens(region) (R11.9 writer shape,
  //    §2.1); return them
```

Pending-record payload (JSON under `pendingLogin(region)`): `{state, verifier,
client_id, redirect_uri, created_at}` — `created_at` via the R11.9
tokens-twin formatter; record shape documented in the module (no Python twin;
it substitutes for Python's in-process locals `flow.py:268-306`).

Code-reuse notes: `OAUTH_PASTE_ERROR` is reused VERBATIM for browser
malformed-return-URL cases — same semantic (an out-of-band-returned redirect
URL fails to parse), same code keeps the cross-language error surface
uniform; the JSDoc notes the name's CLI origin. Only genuinely twin-less
branches get browser-local codes (`BROWSER_NO_PENDING_LOGIN` — added to
`packages/browser/src/errors.ts`, same non-gen-registry rule as §2.3).

### §3.3 Known trap — `urlencode` vs `URLSearchParams` (watchlist entry)

`_build_authorize_url` uses `urlencode` (quote_plus rules); WHATWG
`URLSearchParams` differs on at least `~` (Python leaves `~` bare; WHATWG
percent-encodes it) and `*`. The B8 `buildAuthorizeUrl` already resolved this
("urlencode param order" note, `flow.ts:692`) — the hoist (§3.1) must carry
whatever encoder it uses UNCHANGED, and R2 adds one byte-comparison lock in
core: authorize URL for a fixture containing `~`, space, `+`, `/`, `:` and a
non-ASCII char in `redirect_uri` equals the recorded CPython `urlencode`
output (generate the golden once with `uv run python`, paste it into the test
with a provenance comment — the B0-1 pinned-table pattern). Param order is
insertion order (`response_type, client_id, redirect_uri, state,
code_challenge, code_challenge_method`) and `scope` is INTENTIONALLY OMITTED
(`flow.py:625-627` comment: DCR apps have empty scope ⇒ provider defaults to
all scopes) — omitting it is contract; a reviewer seeing "missing scope" must
find this citation, not a bug.

### §3.4 Layer-3 (R2)

Applicable Python suites translate; browser-inapplicable classes are excluded
WITH file-header citations (R10.2 / phase2-audit A2 style). Dispositions for
every `test_auth_flow.py` class (`tests/unit/test_auth_flow.py`):

| Python class | Disposition |
|---|---|
| `TestParsePastedRedirect` (:215 — 9 tests) | ALREADY translated at B8 against `parsePastedRedirect`; suite FOLLOWS the hoist (import re-point only, assertions untouched). R2 adds browser-context re-takes of the state-mismatch + error-param rows through `completeLogin` (they lock the browser wiring, not the parser) |
| `TestOAuthFlowTokenExchange` (:385 — form params, region URL, error raise) | translated at B8 (node); hoist keeps it green; browser re-take: `completeLogin` posts the same five form fields to `{base}token/` (canned fetch capture, byte-compare the urlencoded body) |
| `TestOAuthFlowRegionUrls` (:759) + `TestOAuthFlowRegionValidation` (:984 — 4 tests) | browser twins: `beginLogin` eu/in authorize-URL host + `OAUTH_CONFIG_ERROR` on invalid/uppercase/empty region |
| `TestOAuthFlowNetworkErrors` (:802 — timeout, connection error, non-JSON, missing access_token; refresh rows) | exchange rows translate against `completeLogin` with canned-fetch rejections/bodies (codes: `OAUTH_TOKEN_ERROR`; fetch rejection normalization per R2.10); refresh rows stay node-only (browser v1 has no refresh — §2.2; header exclusion cite) |
| `TestOAuthFlowLogin` (:88), `TestOAuthFlowPasteFallback` (:286) | EXCLUDED for browser: callback server, port probing, webbrowser, stdin paste are node-only surfaces (R9.2); already translated at B8. Header cites this row |
| `TestOAuthFlowRefresh` (:490), `TestOAuthFlowGetValidToken` (:610) | EXCLUDED for browser v1 (no refresh surface — §2.2 disposition; revisit under the D2-ACCEPTED branch, §4.5) |
| `test_auth_registration.py` | translated at B8 (node cache layer); browser adds: CredentialStore-cached DCR (cache hit iff redirect_uri matches; miss re-registers; 429 + non-success + bad-JSON branches via core `registerClient` — canned) |
| `test_auth_pkce.py` | §1.3 (node re-point) + §3.5 browser RFC re-run |

NEW browser-contract suites (no Python twin — R9.3/plan-4.3 headers):
`redirect-flow.test.ts` (begin/complete happy path against a canned IdP;
pending-record round-trip incl. `created_at` shape; single-use state — replay
of the same returnUrl → `BROWSER_NO_PENDING_LOGIN`; cross-region key
isolation; state generated ≠ predictable (length/alphabet lock);
authorize-URL golden §3.3), `redirect-attacks.test.ts` (state mismatch;
forged state with no pending record; error+error_description propagation;
code-injection attempt with mismatched state loses).

### §3.5 R10.9 throwaway harness (R2) — `throwaway/b9-r2/`

1. **Edge set**: every error branch enumerated — `OAUTH_CONFIG_ERROR`
   (bad region), `OAUTH_PASTE_ERROR` (empty, no-code, no-state, garbage),
   `OAUTH_AUTH_DENIED` (± description), `OAUTH_STATE_MISMATCH`,
   `BROWSER_NO_PENDING_LOGIN` (absent + replayed), `OAUTH_TOKEN_ERROR`
   (network reject, 400, 401, 429, 500, non-JSON 200, missing
   `access_token`), `OAUTH_REGISTRATION_ERROR` (network, 429 with
   Retry-After detail, non-success, bad JSON, missing client_id) — each via
   canned fetch, plus the §2.7-style value edges (`"18.0"`, `"1.5"`, empty
   string, `"𝒳"`) through state/code/description fields.
2. **PKCE RFC vectors vs WebCrypto**: the Appendix-B vector + the §2.7
   CPython differential re-run at the R2 seed (cheap; proves the hoist+re-
   export chain end-to-end from the browser entry).
3. **Fuzz ≥500**: fast-check over `parsePastedRedirect` inputs (URL-ish
   strings, unicode, `+`/`%`-injection, duplicate params) differentially
   against CPython `_parse_pasted_redirect` via ONE batched
   `uv run python` driver (import from `mixpanel_headless._internal.auth.flow`;
   compare code-or-result — the same batching rule as §2.7.3). This is the
   ONLY R2 surface with a live-CPython twin cheap enough to differential-test;
   record seed/counts/divergence table. Known-class divergences (#9/#10
   integer-like key hoisting CANNOT arise — parsed query pairs are arrays)
   — expect ZERO; any divergence blocks.
4. RUN record → `B9-R2-notes.md`; harness lives in `throwaway/b9-r2/` until
   gate cleanup.

### §3.6 R10.10 consumers (R2)

- End users: `beginLogin`/`completeLogin` signatures (§3.2) — pasted above,
  they are the contract; consumed from `packages/browser/src/index.ts`.
- `createBrowserWorkspaceFromStore` (§2.2) consumes the tokens persisted at
  `completeLogin` step 5 (same `CREDENTIAL_KEYS.tokens(region)` — the
  round-trip is locked by one integration test spanning R1+R2 surfaces).
- B9-D2-SPIKE consumes `registerClient`'s exact request body (§4.2 sends the
  IDENTICAL body live) and `beginLogin`'s authorize URL for the residual-gap
  documentation.
- `packages/node` consumes the §3.1 hoisted names via re-export/delegate
  (all signatures unchanged from B8 — their contract is the existing node
  suites).

### §3.7 Done-criteria (R2)

Files on disk + `tsc --strict` clean + §3.4 suites green (browser AND the
untouched-but-re-pointed node suites) + smoke green (hoisted modules bundle)
+ R10.9 RUN record + one TS commit (hoist + node re-point + browser flow
together — no interim dual-home state). No Python-repo change.

## §4 Task B9-D2-SPIKE — the ONLY live procedure of the batch

Model **fable**, effort ≤ high, notes file
`context/phase3/notes/B9-D2-SPIKE-notes.md` (the notes file IS the deliverable
of record; every request/response is transcribed there). Closes plan §8
open-question 3 / §4.3 "Remaining unverified: browser-origin PKCE end-to-end
(DCR client registration + redirect-URI acceptance for third-party origins)".

### §4.1 Budget (HARD, restated from the batch ground state)

1. **Credentials check FIRST**: `uv run mp account test mixpanel-2` — full
   stdout+stderr into the notes; **never suppress stderr** (CLAUDE.md CLI
   rule). If it fails: STOP the live half entirely, classify the spike
   **UNVERIFIABLE**, ship the §4.4-REJECTED docs posture with an
   "unverified, not rejected" wording variant, and record the failure.
2. **≤ 2 DCR registration attempts** (each POST to `mcp/register/` counts,
   success or failure).
3. **≤ 2 Query-API calls** — CONTINGENCY ONLY (§4.3 final paragraph); default is zero.
4. **No other live calls anywhere in B9** — R1/R2/harness traffic is 100%
   canned; the spike itself never calls `token/` or `authorize/` with
   credentials (no headless consent exists — §4.5).
5. Raw `curl -sS` (or an equivalent one-shot script) for the DCR posts —
   NEVER the library paths, so nothing persists into `~/.mp/oauth/` or any
   CredentialStore (§4.6 cleanup duty 1).

### §4.2 Live procedure — DCR redirect-URI acceptance

Request body = BYTE-IDENTICAL to `ensure_client_registered`
(`client_registration.py:106-112`; also core `registerClient` after §3.1 —
cite both in the notes):

```json
{
  "redirect_uris": ["<per-attempt>"],
  "grant_types": ["authorization_code", "refresh_token"],
  "response_types": ["code"],
  "token_endpoint_auth_method": "none",
  "scope": "projects analysis events insights segmentation retention data:read funnels flows data_definitions dashboard_reports bookmarks"
}
```

POST `https://mixpanel.com/oauth/mcp/register/` (us region only — one region
spends the budget where the account lives; regional posture is assumed
uniform and recorded as an assumption).

- **Attempt 1 (the unknown)**: `redirect_uris:
  ["https://spike-b9.example.com/oauth/callback"]` — a third-party **https**
  origin (RFC 2606 reserved domain: provably not attacker-usable, provably
  not localhost). Also send `Origin: https://spike-b9.example.com` on the
  POST (browser-realistic; the App-API ACAO `*` result suggests it is
  ignored, but record the response's CORS headers regardless — free signal).
- **Attempt 2 (control, CONDITIONAL)**: run ONLY if attempt 1 did not return
  2xx: `redirect_uris: ["http://localhost:19284/callback"]` — the known-good
  Python shape (`flow.py:54` + the `redirect_uri_allowed` docstring note at
  `flow.py:55-58`: Mixpanel permits any `http://localhost:<port>/`). A 2xx
  control proves the endpoint is healthy ⇒ attempt 1's rejection is a REAL
  third-party rejection; a failed control means UNVERIFIABLE (endpoint
  down/rate-limited), not REJECTED — never over-claim.

Record for every attempt: full request (headers minus nothing — DCR is
unauthenticated, there is no secret to redact), status, full response body,
`client_id`, and any RFC 7591 management fields
(`registration_access_token` — REDACT its value to first 8 chars if present —
and `registration_client_uri`).

### §4.3 Classification + follow-through

| Outcome | Criterion | Follow-through |
|---|---|---|
| **ACCEPTED** | attempt 1 → 2xx with a `client_id` | (a) construct the authorize URL via the SHIPPED `buildAuthorizeUrl` with that client_id + the third-party redirect (no navigation, no credentials — URL construction is offline); (b) OPTIONAL, inside the remaining budget: ONE unauthenticated `curl -sS -o /dev/null -w '%{http_code} %{redirect_url}'` GET of the authorize URL with `redirect: manual` semantics — a login-redirect/200-login-page proves only URL well-formedness (record exactly that, no more); (c) write the §4.5 residual-gap paragraph; docs posture: Tier C ships PKCE-in-browser ENABLED, labeled "DCR accepts third-party https redirect URIs (verified 2026-08-16); end-to-end browser consent/exchange verified in Phase-4 live burn-in" |
| **REJECTED** | attempt 1 → 4xx AND control → 2xx | docs posture = the plan-§4.3 fallback VERBATIM: "Tier C ships with `oauth_token` (server-minted, handed to browser) first-class; PKCE stays Node-only until resolved." The R2 redirect-flow code + tests STILL SHIP (R9.3 mandates the surface; it is contract-tested against a canned IdP) but the browser README + `redirect-flow.ts` module JSDoc carry the fallback wording and mark the flow "not usable against live Mixpanel today — tracked for Phase 4"; `beginLogin` stays exported (no artificial gate — the server, not the library, is the blocker; record this shipping decision as the packet's reading of R9.3-vs-§4.3 precedence) |
| **UNVERIFIABLE** | creds check failed, or attempt 1 non-2xx AND control non-2xx | REJECTED docs posture with "unverified" wording; Phase-4 ledger entry says re-run the spike, budget 2 attempts, before burn-in |

The Query-API contingency (≤2 calls): used ONLY if the arbiter
of the R1/R2 review pairs questions whether the Phase-0 CORS result still
holds (e.g. a reviewer flags a changed ACAO posture): one
`curl -sS -D-` preflight-style probe per question, `Origin:
https://spike-b9.example.com`, against `/api/query/` on the mixpanel-2
project — never by default.

### §4.4 What the spike does NOT do

No `token/` POST (no code exists to exchange). No `authorize/` with a logged-
in session (that requires a real browser + user consent — Phase 4). No
region sweep. No deletion of created clients (§4.6). No retry outside the
attempt caps — a flaky network failure inside the caps is recorded and
counted.

### §4.5 The residual gap (write it HONESTLY, verbatim structure)

Even under ACCEPTED, three things remain unverified without a real browser
session: (1) authorize-time `redirect_uri_allowed` enforcement for the
registered third-party URI (DCR storing it ≠ authorize honoring it — the
`flow.py:55-58` docstring proves the check is a distinct code path); (2) the
consent screen issuing a code to that redirect; (3) a browser-origin
`token/` POST succeeding cross-origin (the token endpoint's CORS posture was
NOT in the Phase-0 spike table). The batch notes + Phase-4 outbound ledger
name all three as the "browser PKCE e2e" live-auth scenario (plan §6 burn-in
already reserves it — `B8-notes.md` outbound "live auth scenarios"). The
docs never claim e2e verification under any outcome of this spike.

### §4.6 Cleanup duties

1. **No stray local state**: the spike uses raw curl — assert (and record)
   that `~/.mp/oauth/` mtimes are unchanged and no repo file outside
   `context/phase3/notes/` was touched. Nothing beyond what the flow itself
   persists exists, because the flow is never run.
2. **Server-side residue**: every created `client_id` is recorded in the
   notes under a "registered clients (residue)" heading with its
   redirect_uri and any management URI — Mixpanel DCR exposes no documented
   delete in our Python source; deletion is NOT attempted (budget + no
   contract); the Phase-4 ledger carries a "clean up spike DCR clients if a
   management API exists" line.
3. Notes file finalized with: budget ledger (attempts used / calls used),
   classification, docs wording as landed, residual-gap paragraph, and the
   commit hashes of the docs commit (TS) + notes commit (Python).

Done-criteria (D2-SPIKE): classification recorded with evidence; ≤ budget;
docs wording landed in `packages/browser` README + `redirect-flow.ts` JSDoc
(one TS commit); notes committed (Python repo); zero non-notes local residue.

## §5 Batch gate — Phase-3 TERMINAL gate + closing duties

Model **fable**, effort ≤ high. Runs after both module arbiters' GO + the
spike classification. Notes: finalize `context/phase3/notes/B9-notes.md`.

### §5.1 Corpus HOLD (the inverted gate check)

B9 flips NOTHING (`batch-status.ts` untouched — no owned prefix; assert via
`git diff --stat` that the gate commit does not touch it). `npm run
conformance` must read **exactly 3,251 PASS / 0 FAIL / 0 UNPORTED** — any
delta is a REGRESSION introduced by this batch (prime suspects: the §1 node
pkce migration and the §3.1 hoist — both touch modules on the
`oauth_flow.refresh_tokens` vector path). Archive the report as
`context/phase3/reports/<date>-b9-gate.json` (Python repo) exactly like the
eight predecessors.

### §5.2 Build + smoke + regression

1. `npm run check` green — now INCLUDING the promoted two-entry browser
   smoke (core + browser, §2.5); `just check` green on the Python side (the
   batch adds Python-repo commits: packet, notes, reports, playbook flip).
2. **Differential full-suite regression** (P3-7): oracle-py ↔ oracle-ts over
   the ENTIRE registered surface — one FRESH seed AND a re-run of ALL prior
   gate seeds recorded in `differential/oracle/RUN.md` (B0…B8 rows). Zero
   unexplained divergences; shrunken repros to
   `conformance/differential/repros/` block the gate. Append the terminal
   RUN record. (B9 adds no oracle families — the mechanical
   newly-registered-api probe of P3-2e item 3 is vacuous this batch; say so
   in the RUN record rather than skipping silently.)
3. The two direct-CPython differentials (§2.7.3 PKCE, §3.5.3 redirect-parse)
   re-verified from their recorded seeds (spot-check tier, review item 5
   already did full re-runs).
4. `throwaway/b9-r1/` + `throwaway/b9-r2/` REMOVED after both arbiters'
   sign-off (P3-2c standing rule).

### §5.3 Phase-3 CLOSING duty 1 — the summary block (`B9-notes.md`)

A "Phase 3 — CLOSED" block containing, minimally: the batch ledger
B0→B9 (gate dates, commits, PASS-count trajectory 533 → 1,528 → … → 3,251/0/0
from the archived reports); final corpus pin `70c904dc` + N=72 authored;
the discrepancy register status (#1–#15, with #13 CLOSED-FIXED); rulebook
amendments filed during the phase (R11.8, R11.9); escalations (none through
B8 — update if B9 changes that); the two-tier model program observation
rows (per-batch notes "tier observations"); the B9 spike classification; and
the §5.5 outbound ledger by reference.

### §5.4 Phase-3 CLOSING duty 2 — playbook status flip

`context/phase3/design/phase3-playbook.md` header `**Status**:` line gains
"**PHASE 3 COMPLETE** (B9 gate closed <date>, 3,251/0/0 held; terminal gate
report `context/phase3/reports/<file>`)" — a follow-up commit on the Python
support branch, same commit as (or adjacent to) the notes finalization. Do
not rewrite history sections; the flip is additive (one line + a pointer to
the B9 notes summary block).

### §5.5 Phase-3 CLOSING duty 3 — the outbound ledger to Phase 4

Written into `B9-notes.md` (and referenced from the summary block) as the
SINGLE collection point Phase-4 planning reads. Collect, with citations —
this list is the packet's rendering of the accumulated items; the gate task
re-verifies each against its source before writing:

| # | Phase-4 item | Source of record |
|---|---|---|
| 1 | **O1** — `flow.ts:898` `response_data` carries the full 200 token payload into refresh-error details (verbatim `flow.py:596-605` parity); re-examine only if a live IdP returns secrets the error surface should not carry | pair-B lens-1 O1, `B8-notes.md` Phase-4 ledger line 1 |
| 2 | **The Python-fix queue** (R10.7: Python-first fix → re-record → re-pin → TS follows; NONE fixed during Phase 3 by design): (a) frequency-filter clause shape (`context/phase1/addendum/frequency-filter-probe.md`); (b) `dataGroupId` int-vs-string threading (`context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md`); (c) `_handle_response` 403 `TypeError` on truthy non-dict/non-str JSON bodies (`context/phase3/bug-reports/python-handle-response-403-typeerror.md`) | the bug-reports dir + `B8-notes.md` "Open R10.7 items carried forward" |
| 3 | **The JsonNumber round-trip gap** — in the LIBRARY result path a >2^53 integer token collapses at `JsonNumber.toNumber()` before any consumer sees it (TS imprecise/±Infinity where CPython keeps the exact int) — the sanctioned #6/#7 class, disclosed at `B6-notes.md:190`; re-examine if Phase-4 burn-in sees live event counts or ids beyond 2^53 | `B6-notes.md:190`; playbook discrepancies #6/#7 |
| 4 | **Live-parity setup** (plan §6 Phase 4): nightly full-corpus replay, fresh-seed fuzz, live-suite parity, ≥4 green nights; PLUS the live-auth scenarios with no Phase-3 oracle — real IdP refresh, real browser login, real DCR, and the §4.5 browser-PKCE e2e triple (authorize-time redirect enforcement, consent/code issuance, token-endpoint CORS) | plan §6; `B8-notes.md` outbound; §4.5 here |
| 5 | Sanctioned TOCTOU residue of the R9.2 fd-hardening drop (`io-utils.ts` header) | `B8-notes.md` Phase-4 ledger line 2 |
| 6 | Standing discrepancy-class re-examine triggers: #6/#7/#11/#12/#14/#15 (+ #9/#10 residual-site HUMAN-CALL, still open, optional, non-blocking) | playbook discrepancy log; `B8-notes.md` |
| 7 | D2 spike residue: registered client_id cleanup if a management API exists (§4.6.2); spike re-run if UNVERIFIABLE (§4.3) | §4 here |
| 8 | Browser refresh surface (deferred out of v1 — §2.2/§3.4 disposition): add `refreshTokens`-over-CredentialStore if/when the D2-ACCEPTED e2e lands in burn-in | §2.2 here |

### §5.6 Gate done-criteria

§5.1 report archived + §5.2 all green + `throwaway/` gone + §5.3 block +
§5.4 flip + §5.5 ledger + batch-notes finalized + commits: TS gate commit on
`main`; Python docs/report/flip commits on the support branch. LOCAL ONLY,
both repos. **This closes Phase 3.**

## §6 Doubled blind review protocol (P3-3 auth doubling — B9 instantiation)

Per module shard (R1, R2): **two independent review pairs + one arbiter**
(4 reviewers + 1 arbiter per shard; all fable). The D2-SPIKE gets ONE
reviewer (procedure/budget/claims audit — it produces no library code) whose
findings go to the R2 arbiter.

- **Pair A** receives: this packet + the Python sources cited per shard +
  the TS diff + the R10.9 RUN records.
- **Pair B (blind)** receives: the Python sources + the TS diff + the R9.3 /
  plan-§4.3 contract text ONLY — NOT this packet's §2/§3 rationale prose and
  NOT pair A's findings (the B7/B8 blind-pair mechanics verbatim;
  independence is the point — a pair-B reviewer re-deriving a different
  SA-refusal path enumeration than §2.3 is exactly the desired check).
- Every reviewer executes the P3-2(d) items 1–5, with these B9-specific
  mandatory checks: (R1-1) §1.3 assertion-survival diff on the migrated pkce
  suite; (R1-2) base64url alphabet/padding audit of the core encoder (the
  §1.2 wrong-alphabet trap); (R1-3) SA-refusal path hunt — attempt to
  construct a browser workspace/header path that reaches
  `accountAuthHeader` with a `service_account` without hitting a §2.3 gate
  (success = blocking finding); (R1-4) the localStorage security-warning
  text exists and covers XSS/persistence/origin scope; (R1-5) eslint+smoke
  boundary actually covers `packages/browser` (introduce a scratch `node:fs`
  import, confirm BOTH checks fail, revert — record in the review notes);
  (R2-1) §3.1 hoist honesty — moved code byte-diffed against its B8 home
  (only mechanical lifts allowed), node suites unweakened; (R2-2) §3.3
  urlencode golden provenance; (R2-3) single-use pending-state ordering
  (delete BEFORE exchange — a reviewer must check the failure branch too:
  an exchange failure after deletion must NOT resurrect the state; replay
  after failed exchange is a fresh `beginLogin`, document + test); (R2-4)
  error-code audit: every thrown code is either a `flow.py`-cited Python
  code or an enumerated `BROWSER_*` constant — no ad-hoc strings (R5).
- Arbiter: resolves splits, verifies there are no bindings to check (and
  says so), verifies the §3.1 STOP-condition wasn't silently bypassed,
  files R10.4 amendments on ≥3 recurrences, GO/NO-GO per shard.

## §7 Cautions (known traps, all cited)

1. **Wrong-alphabet base64** (§1.2): standard-vs-url alphabet errors pass
   every length assertion; only the RFC Appendix-B vector and the CPython
   differential catch them. Never reuse `base64EncodeUtf8`.
2. **`urlencode` ≠ `URLSearchParams`** (§3.3): `~`/`*`/space handling —
   carry the B8 encoder through the hoist unchanged; golden-lock it.
3. **Scope omission is contract** (§3.3): no `scope` param on the authorize
   URL (`flow.py:625-627`); the DCR body DOES carry the advisory scope
   string (`client_registration.py:46-53`) — two different surfaces, do not
   "fix" either direction.
4. **Async migration ordering** (§1.3): `PkceChallenge.generate()` becomes
   thenable — a forgotten `await` yields a Promise whose `.verifier` is
   `undefined` and TypeScript catches it ONLY if the migration keeps strict
   types end-to-end (no `any` laundering in tests; `@typescript-eslint`
   no-floating-promises is already on — do not disable it locally).
5. **`fromTokenResponse` clock seam** (B8 §0.3.2): browser token parsing
   goes through core `fromTokenResponse(data, {now})` — thread the §3.2
   `now` option; never read the ambient clock in the flow (tests freeze it).
6. **R11.9 writer shapes** (§2.1): `+00:00` for tokens-twin fields, `Z` for
   pydantic-JSON-twin fields — mixing them is the exact 8×-recurrence that
   forced the amendment.
7. **#9/#10 integer-like-key hoisting**: the pending-login record and store
   payloads are OBJECTS — keep their key sets fixed and non-numeric (they
   are: `state`/`verifier`/`client_id`/`redirect_uri`/`created_at`), and no
   ordering contract exists on them; do not introduce one.
8. **Do not touch `batch-status.ts`, `bindings.ts`, or the runner** — zero
   rig changes are in scope; any perceived need is an escalation (P3-3 rig
   row would demand a fable rig task, and B9 should not have one).
9. **`/api/app/me` is minutes-slow live** (plan §4.3 implementer note) —
   nothing in B9 may put it on any code path it isn't already on; the spike
   never calls it.
10. **Hook discipline** (Python repo): `uv run python -m pytest` spelling;
    never bare `python`; batched drivers for the differentials (§2.7.3).

## §8 R9.3 traceability map (done-criterion: every R9.3 requirement → shard)

| R9.3 requirement (rulebook `:266-270`) | Shard · section |
|---|---|
| "injectable `CredentialStore`" | R1 §2.1 (interface in core per plan §4.1; injection points §2.2 options + §3.2 options) |
| "default in-memory" | R1 §2.1 `InMemoryCredentialStore` + §2.2 default |
| "documented localStorage adapter with security warning" | R1 §2.1 `LocalStorageCredentialStore` + warning REQUIREMENT + §2.6 warning-exists test + §6 check R1-4 |
| "redirect-based PKCE (WebCrypto)" | §1 (WebCrypto primitives, core) + R2 §3.2 (redirect flow) + §3.3/§3.5 locks |
| "`oauth_token` mode first-class" | R1 §2.2 (`browserSession` / `createBrowserWorkspace` — the shortest path in the package; README leads with it per the D2 Tier-C table) |
| "Service-account Basic auth refused at runtime in browser builds with an explanatory error" | R1 §2.3 (five enumerated paths, coded `BROWSER_SERVICE_ACCOUNT_REFUSED`, explanatory-message requirement) + §2.6/§2.7 locks + §6 R1-3 hunt |
| (parenthetical) "Export API… Node-only" | R1 §2.4 transport refusal + docs |
| plan §4.3 "Remaining unverified… verify during B9; fallback documented" | D2-SPIKE §4 (procedure, classification, fallback wording verbatim, residual gap) |
| plan §4.1 "core/auth PKCE primitives (WebCrypto)" | §1 ruling |

---

**Done for this packet (task B9-DL)**: PKCE-placement ruling analyzed and
issued with the node-migration spec + zero-behavior-change proof plan (§1);
R1/R2 named in dispatch order with both content re-mappings recorded (§0.2);
every R9.3 requirement mapped to a shard (§8); D2-SPIKE live procedure with
explicit restated budgets, classification table, honest residual gap, and
cleanup duties (§4); per-shard R10.10 consumer lists (§2.8, §3.6), R10.9
harness specs covering SA-refusal-every-path, CredentialStore contract
probes, PKCE RFC vectors vs WebCrypto, state mismatch/replay, and
token-exchange error branches (§2.7, §3.5), and done-criteria (§2.9, §3.7);
gate spec with corpus-HOLD 3,251/0/0, two-entry browser smoke, fresh-seed +
all-prior-seeds differential regression, and the three Phase-3 closing
duties incl. the collected Phase-4 outbound ledger (§5).

## §9 Addendum — B9-D2-SPIKE outcome (ratified result, written by the spike task)

**Executed 2026-08-16 (local) / 2026-08-17 UTC. CLASSIFICATION: ACCEPTED**
(§4.3 row 1: attempt 1 → HTTP 201 with `client_id`
`ClI8BeFoFjq1Vn1SbdpiufvxvRvCwAbFtaMaXRvo` for
`redirect_uris: ["https://spike-b9.example.com/oauth/callback"]`; the
localhost control did not run — conditional on non-2xx). Budget: creds
check 1/1 PASSED, DCR 1/2, Query-API 0/2, plus the §4.3(b) sanctioned
optional authorize GET (302 → login with the full authorize URL as `next`
— URL well-formedness only). Evidence of record:
`context/phase3/notes/B9-spike.md` (dispatch-named; supersedes the §4
filename `B9-D2-SPIKE-notes.md`, which is a pointer).

**Tier-C shipping posture (plan §4.3): PKCE-in-browser VIABLE — ships
ENABLED.** The fallback ("`oauth_token` first-class; PKCE stays Node-only
until resolved") is NOT triggered; `oauth_token` remains first-class and
README-leading regardless.

**Docs-facing wording (as landed, TS repo — `packages/browser/README.md`
"PKCE-in-browser status" + `redirect-flow.ts` module JSDoc)**:

> **PKCE-in-browser ships ENABLED.** DCR accepts third-party https
> redirect URIs (verified 2026-08-16); end-to-end browser
> consent/exchange verified in Phase-4 live burn-in.
>
> Not yet verified without a real browser session (tracked as the
> Phase-4 "browser PKCE e2e" live-auth scenario; these docs claim no
> end-to-end verification): (1) authorize-time `redirect_uri_allowed`
> enforcement for the registered third-party URI; (2) the consent screen
> issuing a code to that redirect; (3) a browser-origin `token/` POST
> succeeding cross-origin.

Gate consumption (§5.3/§5.5): spike classification = ACCEPTED; ledger row
7 residue = one client id (above, no management URI returned — cleanup
only if a management API exists); ledger row 8 (browser refresh) now sits
on the D2-ACCEPTED branch — burn-in e2e remains the precondition. Free
signal recorded: the DCR endpoint answered a third-party `Origin` with
`access-control-allow-origin: *` (adjacent-favorable, NOT evidence about
`token/`). Regional posture (eu/in) assumed uniform — us only was probed.
