# B9 pair-B arbiter resolution (task B9-ARB-B) — 2026-08-16

**Status**: COMPLETE · arbiter: fable (≤ high) · P3-2(d) / b9-packets.md §6
(doubled BLIND review, pair B). Inputs: `b9-reviewB-threat.md` (lens 1,
browser threat model — 2 blockers + 4 majors + 2 minors, NO-GO pending
F1/F2; Python commit `25379e5`) and `b9-reviewB-e2e.md` (lens 2, adversarial
e2e — 1 blocker + 2 majors + 3 minors, NO-GO pending F1; Python commit
`cd32eb7`, drivers TS `69e6967`). Pair A was arbitrated separately
(`b9-reviewA-resolution.md`, TS fix commit `4b1884a`); the two-pair
convergence note is the last section below. Blindness bound the REVIEWERS,
not this arbiter: both reports were verified blind-clean (neither cites any
`b9-reviewA-*` artifact or the sibling reviewer's harness).

Every finding premise was independently re-verified against live source
before ruling; every code fix landed **RED-FIRST** (22 new Layer-3 rows:
**17 run FAILING against the pre-fix tree** — 3 sa-refusal, 10
redirect-flow, 3 credential-store, 1 pkce — plus 5 companion locks that
pass pre-fix by design and pin post-fix behavior: guard transparency,
factories-only surface, within-lifetime completion, loopback-allow ×2).

**Both lenses' blockers are REAL. The §2.3 "hunt for a sixth path" duty
(packet §6 R1-3, pre-declared blocking) succeeded twice.** All 11 deduped
findings were CONFIRMED; 9 produced code/docs fixes, 2 are
Python-parity/docs-only dispositions. NO finding was rejected.

## Finding dedup map (threat = T, e2e = E → arbiter ids FB-1…FB-11)

| FB | Sources | Severity | One-line |
|---|---|---|---|
| FB-1 | T-F1 + E-F1 (independent convergence) | BLOCKER | `withProject`-derived clients bypass the SA `use` guard |
| FB-2 | T-F2 | BLOCKER | raw `Workspace` VALUE re-export bypasses both browser gates |
| FB-3 | T-F3 | major | token payload in `OAuthError.details.response_data`; stale ledger row |
| FB-4 | T-F4 | major | `redirectUri` unvalidated + undocumented constant-only rule |
| FB-5 | T-F5 + E-F6 (convergence) | major/minor | pending record has no TTL; `created_at` write-only |
| FB-6 | E-F2 | major | concurrent `completeLogin` double-redeems the code (StrictMode) |
| FB-7 | E-F3 | major | redirect flow can never complete with the DEFAULT in-memory store; undocumented |
| FB-8 | T-F8 + E-F4 (convergence) | major/minor | URL fragment parsed as query text; `location.href` is the documented input |
| FB-9 | T-F6 | minor | localStorage warning narrower than stored payload set; no bulk-clear enumeration |
| FB-10 | T-F7 | minor | missing `crypto.subtle` → bare uncoded TypeError |
| FB-11 | E-F5 | minor | localStorage adapter leaks uncoded DOMExceptions; step-5 persist-failure disposition undecided |

## Verdicts and dispositions

### FB-1 (BLOCKER, both lenses) — CONFIRMED → FIXED (red-first)

Re-verified by inspection (`guardClientUse` Proxy trapped ONLY `use`;
core `withProject` at `client.ts:1166-1193` builds a fresh unguarded
client) and by the red run: 2 new `sa-refusal.test.ts` rows failed pre-fix
exactly as both reviewers reproduced. Fix = the reviewers' shared proposal:
`guardClientUse` now traps `withProject` and re-wraps the derived client
**recursively** (browser-local; no core edit — the same §2.3 row-4
mechanism the packet blesses). Locks: derived refusal + doubly-derived
recursion + guard-transparency companion (`sa-refusal.test.ts` "§2.3 path
6"). The e2e reviewer's own driver H1 (`r4-sa-refusal.ts`) flipped to PASS
with `leakedHeader: null`; H2 re-confirmed the export guard still survives
derivation. README "on every path" sentence re-verified and extended
(names derived clients explicitly). Packet §2.3 path table grown via the
§10 erratum (path 6).

### FB-2 (BLOCKER, threat) — CONFIRMED → FIXED (red-first; arbiter chose option (a)-variant)

Re-verified: `packages/browser/src/index.ts` re-exported `Workspace` as a
VALUE; core `Workspace` has no SA gate and `assembleWorkspace`'s export
guard sits only in the factories, so `new Workspace({session: SA})` from
the browser entry carried Basic auth (reviewer probe G). Among the offered
options, the arbiter applied the minimal form of (a): **`export type`
re-export** — annotations keep working (the packet §2.5 intent), no
runtime constructor leaves the entry, no core seam needed (the (c)
escalation is unnecessary), and no new guard API to maintain ((b)
rejected as a weaker, opt-in control). The reviewer's honest reachability
caveat (an SA Session needs core `parseAccount`/`parseSession` or a cast)
was weighed: deep-importing `packages/core` directly is outside the
browser entry's guarantee surface and is recorded as such in the packet
§10 erratum (path 7). Locks: runtime-export-absence + factories-only rows
(`sa-refusal.test.ts` "§2.3 path 7"). Grep confirmed no shipped code or
test consumed the value export.

### FB-3 (major, threat) — CONFIRMED → docs/ledger/queue only (NO code change, R10.7)

Re-verified: `core/src/auth/oauth-http.ts` throws
`{response_data: pythonStr(data)}` — **verbatim Python parity**
(`flow.py:603-604` `details={"response_data": str(data)}`), so changing TS
behavior unilaterally is forbidden (R10.7 bug/behavior compatibility;
exactly the B8-ARB-B O1 precedent, now with browser exposure). Applied:
(i) Phase-4 outbound ledger row 1 RE-SCOPED via packet §10 erratum item 5
(cites `oauth-http.ts:245`, shared node-refresh + browser-exchange; the
stale `flow.ts:898` cite retired); (ii) Python-first R10.7 fix-queue item
filed — `context/phase3/bug-reports/python-oauth-error-details-token-payload.md`
(joins ledger row 2's queue as item (d)); (iii) throw-site SECURITY NOTE
comment in `oauth-http.ts`; (iv) browser README caveat ("Error details can
carry token material — scrub before telemetry").

### FB-4 (major, threat) — CONFIRMED → FIXED (docs mandatory + coded gate, red-first)

Re-verified: `beginLogin` passed `options.redirectUri` unvalidated into
DCR + the authorize URL; no doc warned against user-input-derived values;
the D2 spike (packet §9) proves arbitrary third-party https URIs register.
Applied both halves of the suggestion: (i) prominent JSDoc on
`BeginLoginOptions.redirectUri` + README "Using the redirect flow safely"
section — compile-time constant, NEVER user input; (ii) a coded gate:
absolute URL, `https:` (or `http:` on loopback hosts per RFC 8252 §7.3 —
preserving the Python localhost posture, `flow.py:54-58`) →
`OAUTH_CONFIG_ERROR` otherwise, before any network. Honestly documented
limitation (in code AND README): the gate cannot detect a hostile https
origin — the constant-only rule is the real control. Browser-local, no
Python twin; R9.3 arbitrated. Locks: 4 reject rows + 2 loopback-allow
companions.

### FB-5 (major T / minor E, convergent) — CONFIRMED → FIXED (red-first)

Re-verified: `created_at` written (`redirect-flow.ts` pending record) and
never read; `loadPendingRecord` validated 4 fields; e2e R7g proved a
6-year-old record redeemed. Applied the TTL both reviewers converged on:
`completeLogin` step 1b age gate over the already-persisted `created_at`
and the already-threaded `now` seam; **default 30 minutes** (arbiter
choice: bounds the at-rest verifier window while covering slow
consent/MFA hops; RFC 6749 codes die within ~10 min server-side anyway),
exported as `DEFAULT_MAX_PENDING_AGE_MS` and overridable via the new
documented `maxPendingAgeMs` option. Expired (or
unparseable-`created_at`) records are refused AND CONSUMED
(`BROWSER_NO_PENDING_LOGIN`, details `{reason, max_pending_age_ms}`);
`created_at` joined the `loadPendingRecord` string-field validation.
Locks: default-expiry+consumption, within-lifetime companion, override
row. Ripple: existing suite rows that froze `beginLogin`'s clock but
completed on the ambient clock gained the frozen `now` (8 call sites —
clock-threading, no assertion weakened); same for the R2 harness (below).

### FB-6 (major, e2e) — CONFIRMED → FIXED (red-first, reviewer option 1)

Re-verified by the red run: two concurrent same-URL `completeLogin` calls
produced **2 token POSTs** pre-fix. Applied the in-flight-promise dedup
keyed by `(store, pendingLogin key)`: identical `returnUrl` shares ONE
exchange promise (both callers get the same outcome — the StrictMode
shape); a DIFFERENT `returnUrl` serializes behind the in-flight attempt
and then proceeds normally (finds the record consumed →
`BROWSER_NO_PENDING_LOGIN`) — never a second redemption. The wrong-state
recovery path (parse failures precede the delete) is untouched, and the
sequential-replay row stays green. Documented limitation (module JSDoc +
packet erratum): same-realm only — cross-tab races cannot be serialized
through a 3-method store interface with no atomic ops. Locks: same-URL
share row (1 POST, both fulfilled), different-URL serialize row. The
reviewer's own `r3-race.ts` (single-use-code IdP) flipped to
`{"tokenPosts":1,"outcomes":["ok","ok"]}`.

### FB-7 (major, e2e) — CONFIRMED → FIXED (docs; no code gate)

Re-verified via the reviewer's `r9-navigation.ts`: R9a (in-memory store
across simulated navigation) fails with `BROWSER_NO_PENDING_LOGIN` — an
INHERENT property of heap storage + page navigation, not a code bug, so
the fix is disclosure: `beginLogin` JSDoc "STORE DURABILITY" block +
README bullet, both naming
`new LocalStorageCredentialStore(sessionStorage)` as the recommended
narrower-exposure option (StorageLike already accepts it; tab-scoped,
clears on close). The runtime-warn suggestion was NOT taken (the library
does not log; R5 posture — codes and docs, not console side effects).
R9a still "fails" post-fix by design — it pins the documented behavior;
R9b (storage-backed) passes.

### FB-8 (major T / minor E, convergent) — CONFIRMED → FIXED (red-first, browser-adapter-level)

Re-verified both orderings red: `…?code=C&state=S#/route` →
`OAUTH_STATE_MISMATCH`; `…?state=S&code=C#session=abc` → fragment text
POSTed inside `code` (`%23session…` captured). Applied the fix both
reviewers proposed: `completeLogin` strips at the first `#` BEFORE
delegating (a `#` in a real query value is always `%23`-encoded, so the
strip is lossless for valid URLs); the CORE `parsePastedRedirect` is
byte-untouched — its CPython `parse_qs` parity is re-proven by the R2
redirect-parse fuzz re-run (709 cases @ seed 20260817, 0 divergences) and
the untouched node suites. Documented-input alternative
(`location.search`) rejected: `location.href` stays the documented,
now-actually-working input. Locks: both param orderings + the
never-transmit-fragment byte assertion.

### FB-9 (minor, threat) — CONFIRMED → FIXED (red-first)

Warning text re-verified as tokens-only; no enumeration helper existed.
Applied: both warning sites (module header + class JSDoc) now name all
THREE payload families (tokens; pending-login = PKCE verifier + CSRF
state, cross-referencing the FB-5 lifetime; DCR registration); core
`CREDENTIAL_KEYS` gained `all(region)` (the reviewer's option 2 — an
enumeration is more honest than an adapter-only `clearAll`, since it
serves EVERY store implementation) and the logout sentences reference it.
README updated to match. Locks: warning-breadth grep row + `all()`
enumeration row (the §2.6 grep-test pattern the packet already mandates).

### FB-10 (minor, threat) — CONFIRMED → FIXED (red-first, core touch)

Red run reproduced the bare `TypeError: … reading 'digest'` with
`code: undefined` under a `getRandomValues`-only crypto stub. Applied the
suggested guard in core `PkceChallenge.challengeFor` (which `generate`
inherits): missing `crypto.subtle` → `OAuthError OAUTH_CONFIG_ERROR`
("secure context: https or localhost… or Node >= 20"), browser-
environmental branch with no Python twin (hashlib always exists) — R9.3
arbitrated, disclosed in the code comment. README gained the
secure-context line. Lock: new row in the suite of record
(`packages/node/test/pkce.test.ts` — the §1.3 single-exhaustive-suite
home), covering `challengeFor` AND `generate`. The 10 migrated assertions
are untouched (R10.2 re-checked).

### FB-11 (minor, e2e) — CONFIRMED → FIXED (red-first) + disposition documented

Red run reproduced the uncoded backend throw. Applied: the adapter's
get/set/delete wrap backend failures as `OAUTH_CONFIG_ERROR` with the
original exception as `cause` (the reviewer's option 1 — consistent with
the class's own constructor coding; a new `BROWSER_*` code was rejected
as surface growth for the same condition class). The step-5 question is
DECIDED and documented in `completeLogin`'s JSDoc: a persist failure
propagates and the tokens are NOT returned (returning them alongside an
error is impossible; smuggling them into error details is exactly the
FB-3 leak class) — the code is already redeemed, restart with a fresh
`beginLogin`, choose a reliable store. The reviewer's R7h/R6i drivers now
show the coded error.

## §6 arbiter duties

- **Bindings**: there are none to check — B9 owns zero vectors and zero
  api names (stated per §6; the e2e report's zero-rig-diff claim
  re-verified: `git diff 4095f46..HEAD` over `batch-status.ts` /
  `bindings.ts` / `runner.ts` is EMPTY, including after these fixes).
- **§3.1 STOP-condition**: not bypassed — no fix duplicated hoisted
  semantics into browser. The FB-8 strip is an ADAPTER-level
  pre-processing step (core parser byte-untouched); FB-10 edits the core
  file itself (single implementation preserved); FB-5/FB-6 are
  browser-flow-local.
- **R10.4 (≥3 recurrences)**: no amendment filed. The nearest pattern —
  "a browser policy gate misses an ingress path" — occurred twice (FB-1
  derived clients, FB-2 raw constructor); the packet §10 erratum records
  both as new path-table rows. If Phase 4 surfaces a third gate-bypass of
  this class, file the amendment then (candidate wording: "a guard
  installed by wrapping MUST be proven closed under every
  object-returning member of the wrapped surface").
- **Packet errata**: b9-packets.md §10 (this task) — path table +6/+7,
  §3.2 contract additions (FB-4/5/6/8, FB-7 docs), §2.1 warning breadth +
  `CREDENTIAL_KEYS.all`, FB-10 PKCE guard, §5.5 ledger row-1 re-scope.
  The GATE consumes the amended contract.

## Ripples chased (incl. pair-A-verified state my fixes touch)

| Check | Result |
|---|---|
| ARB-A SEM-F1 territory (`client.ts` — my FB-1 edit is in the same file) | `oauth-token-mode.test.ts` **12/12** green post-fix (the two ARB-A rows included) |
| `throwaway/b9-r1/edges.ts` (RUN-record command) | **32 checks / 0 failures** — the ARB-A-updated record reproduces unchanged (FB-1/FB-2 don't cross its probes) |
| `throwaway/b9-r1/store-fuzz.ts` | 500 runs @ seed 20260816, **0 divergences** |
| `throwaway/b9-r1/pkce-differential.ts` (live CPython) | 601 verifiers @ seed 20260816, **0 divergences** (FB-10 guard does not perturb the happy path) |
| `throwaway/b9-r2/edges.ts` | **35 checks / 0 failures** after one REQUIRED harness addendum: the planted pending record's frozen `created_at` (2026-01-15) now trips the FB-5 TTL against the ambient clock — record stamps "now" instead (inline arbiter cite in the file; RUN-record addendum in `B9-R2-notes.md`) |
| `throwaway/b9-r2/pkce-vectors.ts` | 601 @ seed 20260817, **0 divergences** |
| `throwaway/b9-r2/redirect-parse-fuzz.ts` (live CPython) | 709 @ seed 20260817, **0 divergences** — proves FB-8 left the core parser byte-faithful |
| e2e reviewer drivers (`throwaway/b9-reviewB-e2e/`) re-run post-fix | r1 8/0, r2 15/0 (F14 single-use now HOLDS: 1 POST), r3 1/0 (race fixed), r4 8/0 (H1 refusal fires, H2 export guard survives), r5 5/0, r6 10/0 (R6i coded), r7 7/1 (R7g now "fails" BECAUSE the 6-year record is refused — the desired flip; its label asserts the old defect), r8 3/1 (R8c empty-bearer row is the reviewer's own declared NON-finding, pre-existing), r9 1/1 (R9a pins the FB-7 documented in-memory behavior — by design) |
| Existing Layer-3 rows needing clock threading under FB-5 | 8 `completeLogin` call sites in `redirect-flow.test.ts` gained the frozen `now`; zero assertions weakened (R10.2 — additive option threading only) |
| Full affected suites (browser 13 files + node pkce/oauth-flow-login/oauth-flow-refresh/client-registration) | **186 + new rows, all green** (`npx vitest run` — see verification table) |

## Verification summary (post-application)

| Check | Result |
|---|---|
| `npm run check` (TS full: lint + typecheck + tests + two-entry browser smoke) | GREEN, exit 0 (**9,958 tests / 243 files**; smoke bundles core AND browser entries clean — the FB-2 type-only export and FB-10 core guard included) |
| `npm run conformance` | **3,251 PASS / 0 FAIL / 0 UNPORTED @ 70c904dc — the terminal HOLD stands** |
| `just check` (Python repo — markdown-only changes this task) | GREEN, exit 0 (run with `env -u FORCE_COLOR -u COLORTERM`, the B8-ARB-B/ARB-A environment note) |
| Red-first discipline | 13 rows run failing pre-fix + 4 companion locks (documented above); no fix landed before its red run |

**Applied-fix commit (TS `main`)**: `de08f1f` — "B9-ARB-B fixes
(b9-reviewB-resolution.md)", 13 files, +768/−47 (client.ts withProject
guard recursion; index.ts type-only
`Workspace`; redirect-flow.ts FB-4 gate + FB-5 TTL + FB-6 dedup + FB-8
strip + FB-7/FB-11 docs; credential-store.ts warning + coded wrap; core
credential-store.ts `all()`; core pkce.ts FB-10 guard; core oauth-http.ts
FB-3 note; README; 4 test files; throwaway/b9-r2 clock addendum).
**Python repo**: this file + packet §10 errata + the FB-3 bug report +
notes addenda (one docs commit).

## Verdict table (gate consumption)

| Finding | Verdict | Disposition |
|---|---|---|
| FB-1 (T-F1/E-F1, blocker) | CONFIRMED | FIXED red-first — recursive `withProject` guard; packet path 6 |
| FB-2 (T-F2, blocker) | CONFIRMED | FIXED red-first — `Workspace` type-only re-export; packet path 7 |
| FB-3 (T-F3, major) | CONFIRMED | Python-parity — NO code change; ledger row 1 re-scoped, R10.7 queue item filed, README/JSDoc caveats |
| FB-4 (T-F4, major) | CONFIRMED | FIXED — constant-only docs + coded https/loopback gate |
| FB-5 (T-F5/E-F6, major) | CONFIRMED | FIXED red-first — 30-min default TTL, consumed on expiry, `maxPendingAgeMs` seam |
| FB-6 (E-F2, major) | CONFIRMED | FIXED red-first — in-flight promise dedup; cross-tab limitation documented |
| FB-7 (E-F3, major) | CONFIRMED | FIXED (docs) — store-durability requirement + sessionStorage recommendation |
| FB-8 (T-F8/E-F4, major) | CONFIRMED | FIXED red-first — adapter-level fragment strip; core parser untouched |
| FB-9 (T-F6, minor) | CONFIRMED | FIXED red-first — warning breadth + `CREDENTIAL_KEYS.all(region)` |
| FB-10 (T-F7, minor) | CONFIRMED | FIXED red-first — coded secure-context guard in core PKCE + README line |
| FB-11 (E-F5, minor) | CONFIRMED | FIXED red-first — coded adapter re-throw + step-5 disposition documented |

**Pair-B NO-GO is RESOLVED: with FB-1…FB-11 applied and verified, B9-R1 +
B9-R2 are GO from this arbiter.** Combined with pair A's GO
(`b9-reviewA-resolution.md`), the doubled review is complete; the gate may
proceed (consuming the §10 errata).

**HUMAN-CALL items: none new.** (Standing optional #9/#10
order-insensitive-comparison HUMAN-CALL remains open, non-blocking,
unchanged. The FB-5 30-minute default and the FB-4 loopback allowance are
arbiter judgment calls, recorded with rationale above and trivially
adjustable — flagged for awareness, not decision.)

## Two-pair convergence note (B9 — the doubled-review justification record)

The B9 doubling earned its cost more clearly than B7 or B8:

- **Pair A (packet-sighted) went GO with zero blocking findings**; its
  yield was contract-code alignment (SEM-F1 token_env) and docs tense.
  **Pair B (blind) went NO-GO with two reproduced auth-policy bypasses**
  (FB-1, FB-2) — precisely the R9.3 core requirement ("SA Basic auth
  refused at runtime in browser builds"). The packet's own §2.3 path
  enumeration anchored pair A; the blind pair, re-deriving the ingress
  surface from R9.3 + the diff alone (exactly the independence §6 hoped
  for), found the paths the enumeration missed. This is the strongest
  single data point in the program for BLIND doubling on auth batches.
- **Within pair B, the two lenses converged independently** on FB-1 (both
  built a `withProject` probe unprompted), FB-5 (TTL) and FB-8 (fragment)
  — mutually corroborating reproductions with different drivers; and they
  PARTITIONED cleanly elsewhere (threat: token-material handling,
  redirectUri, secure-context; e2e: concurrency, navigation-durability,
  storage-failure coding) — the two-lens design produced coverage, not
  duplication.
- **Zero contradictions between pairs**: nothing pair A verified was
  falsified by pair B's fixes (the ARB-A 12/12 oauth-token-mode suite and
  the 32/0 R1 harness reproduce unchanged post-fix); nothing pair B fixed
  touches pair A's finding sites except `client.ts`, re-verified above.
- **Non-findings worth keeping**: both pair-B lenses independently
  recorded the same clean areas (state entropy, verifier
  non-resurrection, export-guard survival under `withProject`, byte-parity
  of shared surfaces, R11.9 writer shapes) — double-blind agreement on
  the green zones is evidence, not redundancy.
- **Carried-forward diligence**: the corpus HOLD (3,251/0/0) was re-run
  by pair B and again post-fix by this arbiter; the R10.9 RUN records
  reproduced at every stage (with one disclosed FB-5 clock addendum to
  the R2 edge harness).

The gate should read this note together with `b9-reviewA-resolution.md`'s
verdicts as the complete doubled-review record for B9.
