# B9 Pair-A Lens-2 review — ASSERTION FIDELITY + BUILD BOUNDARIES

**Status**: COMPLETE · 2026-08-16 · reviewer: pair A, lens 2 (fable, ≤ high).
Scope: all B9 commits since B9-DL — TS `9fcc489` (B9-R1), `009bad7` (B9-R2),
`f6f298b` (spike docs); Python `78c37de` (B9-DL packets), `5f87491` (R1 notes),
`262e873` (R2 notes), `3005bc9` + `85e3337` (spike notes). Spec of record:
`phase3-playbook.md` v1.1 (read fully) + `b9-packets.md` v1.0 (read fully, incl.
the §9 spike addendum). Contract arbiter for twin-less browser behavior:
R9.3 / plan §4.3, citation-for-citation (verified below). Pair-B blindness
honored: no `b9-reviewB-*` file exists yet and none was read.

**VERDICT: GO from this lens. Zero blocking findings; 1 minor doc finding
(packet-inherited wording), 3 observations. Every dispatch check PASSED.**

## 1. R10.2 assertion-weakening diff — every translated test

Test files changed across B9 (`git diff 4095f46..f6f298b --stat -- '*test*'`):
14 files, of which exactly ONE pre-existing suite was modified
(`packages/node/test/pkce.test.ts`); the other 13 are new. No other existing
Layer-3 file was touched anywhere in the batch — the B8 node suites
(oauth-flow-login/refresh, client-registration, callback-server,
settings-headers, query-params-adjacent) are byte-untouched since B8 and
re-run green post-hoist (verified: `npx vitest run packages/node` → 420/420
PASS). That is the packet's §1.3/§3.1 "zero-behavior-change proof" and it holds.

- **`packages/node/test/pkce.test.ts` (§1.3 re-point)**: diffed hunk-by-hunk.
  All 10 assertions survive VERBATIM (9 translated `TestPkceChallenge` rows +
  the RFC 7636 Appendix-B vector row); the only delta is the mandated
  async-adaptation (`await` on `generate`/`challengeFor`) plus header prose.
  Import path unchanged (resolves through the node re-export to core WebCrypto
  — §1.3.1 as specced). No weakened matcher, no dropped row. PASS.
- **`TestParsePastedRedirect` (9 rows)**: lives in the untouched
  `packages/node/test/oauth-flow-login.test.ts`, still importing
  `parsePastedRedirect` from `packages/node/src/auth/flow.ts`, which now
  re-exports the hoisted core function (`flow.ts:169`) — "follows the hoist,
  assertions untouched" exactly as §3.4 row 1 specifies. The moved function
  body was byte-diffed against its B8 home
  (`git show 4095f46:packages/node/src/auth/flow.ts` region 199-244 vs
  `packages/core/src/auth/redirect-parse.ts`): **BYTE-IDENTICAL**. The browser
  re-takes of the state-mismatch + error-param rows exist through
  `completeLogin` (`redirect-attacks.test.ts:62,124`) per the row's mandate.
  PASS.
- **`buildAuthorizeUrl` hoist**: body identical modulo the specced mechanical
  extraction (`this.#baseUrl` → `baseUrl` parameter); node keeps a one-line
  delegate (`flow.ts:639`). The §3.3 urlencode encoder rode through UNCHANGED
  (`urlEncodePairs`) — independently verified, see §4 below. PASS.
- **Browser re-takes vs `tests/unit/test_auth_flow.py`** (dispositions §3.4,
  all header-cited in `redirect-flow.test.ts:1-18`):
  - `TestOAuthFlowRegionUrls:759` → `it.each` eu/in authorize-host twins
    (`redirect-flow.test.ts:105-115`). PASS.
  - `TestOAuthFlowRegionValidation:984` → uk/US/"" rejection twins with
    `OAUTH_CONFIG_ERROR` for BOTH `beginLogin` (:118) and `completeLogin`
    (:321), each also asserting ZERO network captures (stronger than Python's
    constructor-time check). Valid-region acceptance is exercised by every
    us/eu/in happy path. See O3 (message-substring note). PASS.
  - `TestOAuthFlowTokenExchange:385` → the five form fields are locked by a
    **full-body byte-compare in insertion order** (`redirect-flow.test.ts:172`,
    `flow.py:428-434` cite) — strictly STRONGER than Python's five `in`
    substring asserts, plus URL + content-type asserts. PASS.
  - `TestOAuthFlowNetworkErrors:802` exchange rows → rejection / non-JSON-200 /
    missing-access_token / 400-invalid_grant, all coded `OAUTH_TOKEN_ERROR`
    (`redirect-flow.test.ts:334-400`). See O2 (timeout+connect merged into one
    rejection row). Refresh rows excluded WITH the §2.2/§3.4 cite in the file
    header. PASS with observation.
  - `TestOAuthFlowLogin:88` / `TestOAuthFlowPasteFallback:286` /
    `TestOAuthFlowRefresh:490` / `TestOAuthFlowGetValidToken:610` — excluded
    for browser, header carries the R9.2/§2.2 citations verbatim (A2 style).
    PASS.
  - `test_auth_registration.py` → browser adds exactly the §3.4 row's cache
    additions (hit-iff-redirect_uri-matches `:81,:102`, per-region isolation
    `:123`, DCR body byte-compare in Python dict insertion order `:40`, and
    the 429/non-success/bad-JSON/missing-client_id/network branches via the
    hoisted core body `:168-250`); node's untouched B8 suite remains the
    exhaustive lock (header says so). PASS.
  - `test_auth_pkce.py` → §1.3 node re-point (above) + browser RFC re-run
    through the entry point (`pkce-webcrypto.test.ts` — Appendix-B vector +
    86/43 locks, header cites §1.3 item 4 and the single-exhaustive-lock
    R10.8 rule). PASS.
- **TODO(port) triage** (P3-2d item 4): exactly one marker in the B9 surface
  (`packages/browser/src/client.ts:198`, refresh disposition) — owned
  (Phase-4 ledger row 8 + R1-notes "Refresh disposition" section). PASS.

## 2. Contract citations on authored browser-contract tests

Every authored suite header names its contract clause (uncited = finding —
NONE found):

| File | Citation in header |
|---|---|
| `credential-store.test.ts` | R9.3 quoted + b9-packets §2.1, A2 style |
| `token-serialization.test.ts` | §2.1 R11.9 + `storage.py:451-478` / `:526-543` twins + B8 goldens copied WITH CITE (`b8-reviewB-resolution.md` F2 table) |
| `sa-refusal.test.ts` | R9.3 quoted + plan §4.3 Tier C note; each describe names its §2.3 path row; rows 2/5: row 2 has the `@ts-expect-error` fixture (:82), row 5 documented in `redirect-flow.ts` header (:34-36) — per packet (row 5 has no parameter to fixture against) |
| `oauth-token-mode.test.ts` | R9.3 "oauth_token first-class" + plan §4.3 Tier C; Python-twin surfaces named (parseAccount/parseSession, core header path, maybe_scoped_path) |
| `export-refusal.test.ts` | plan §4.3 "Export is Node-only" + D2 spike table; covers §2.4 (a)/(b)/(c) exactly, and derives the origin set from core `ENDPOINTS` (:44 — never restates literals) |
| `redirect-flow.test.ts` | flow.py cites per twinned row + R9.3/plan §4.3 for the adaptation + the four exclusion citations |
| `redirect-attacks.test.ts` | R9.3/plan §4.3 + `flow.py:51-117` codes-verbatim cite |
| `registration.test.ts` | §3.1 hoist + `client_registration.py:92-93` cache rule cite |
| `pkce-webcrypto.test.ts` | §1.3 item 4 + B8 outbound row + R10.8 |
| `core/test/auth/oauth-http.test.ts` | §3.3 + golden provenance command pasted verbatim (B0-1 pinned pattern) |

The R1-4 security-warning check also passes: the adapter JSDoc
(`credential-store.ts:110-131`) states synchronous, origin-scoped,
XSS-readable, readable-by-any-script, survives-logout-unless-deleted, and
in-memory-default-recommended-with-re-login — and the §2.6 source-text grep
test (`credential-store.test.ts:128`) locks each element with a regex.

## 3. Browser package purity + eslint boundary (R1-5 probe EXECUTED)

- Grep of `packages/browser/src`: zero `node:*`/`fs`/`path`/`os`/`undici`
  imports, zero `process` reads, zero `require`. `localStorage`/`globalThis`
  touched ONLY in `credential-store.ts` via the injected `StorageLike`
  parameter (default `globalThis.localStorage`) — §0.4 as specced. Import
  graph reaches only `../../core/src/…` + package-local files; NO
  `packages/node` import exists.
- `eslint.config.js` block now covers
  `files: ["packages/core/**/*.ts", "packages/browser/**/*.ts"]` (src AND
  tests) with updated messages naming R9.3/R9.4.
- **R1-5 probe (run + reverted, per §6)**: appended a scratch
  `import { readFileSync } from "node:fs"` to
  `packages/browser/src/errors.ts` →
  (a) `npx eslint` FAILS (exit 1, no-restricted-imports, the browser-boundary
  message); (b) `node scripts/browser-smoke.mjs` FAILS (exit 1,
  `ERROR: Could not resolve "node:fs"` at the probe line). Reverted; tree
  clean (`git status` empty). The boundary REALLY covers packages/browser in
  both mechanisms.

## 4. Browser-bundle smoke genuinely builds browser + core

`scripts/browser-smoke.mjs` inspected: `entryPoints` is now the two-element
array `["packages/core/src/index.ts", "packages/browser/src/index.ts"]`, one
`build()` call, `bundle: true`, `platform: "browser"`, `write: false`
(+ `outdir` required by esbuild for multi-entry — nothing written; verified
no `dist-smoke/` exists). A `node:*` anywhere in EITHER module graph fails
the whole build (proven live by the R1-5 probe). Wired into `npm run check`
(`package.json:26`). Green run: "core + browser bundled (2,062,785 bytes)".
PASS.

Bonus independent verification: the §3.3 CPython urlencode golden was
REGENERATED live (`uv run python -c "...urlencode(...)"` with the exact
provenance command from the test comment) — output byte-identical to the
pasted golden, including `~` bare, space→`+`, `*`→`%2A`, UTF-8 runs for `ü`.
R2-2 (golden provenance) PASS.

## 5. Corpus HOLD (run, not trusted)

`npm run conformance` at `f6f298b` (= current `main` HEAD):
**3,251 PASS / 0 FAIL / 0 UNPORTED (corpus @ 70c904dc598d)** — the terminal
gate expectation HOLDS after both module shards + the docs commit. PASS.

R10.9 RUN-record reproduction (P3-2d item 5, spot-check tier from recorded
seeds — all four cheap legs re-run):

| Leg | Recorded | Re-run result |
|---|---|---|
| R1 edges (`throwaway/b9-r1/edges.ts`) | 32 checks / 0 fail | 32/0 — reproduces |
| R1 PKCE CPython differential (seed 20260816) | 601 / 0 divergences | 601/0 — reproduces |
| R2 edges (`throwaway/b9-r2/edges.ts`) | 35 checks / 0 fail | 35/0 — reproduces |
| R2 redirect-parse fuzz (seed 20260817) | 709 / 0 divergences | 709/0 — reproduces |

## 6. Spike budget compliance + redaction discipline

From `context/phase3/notes/B9-spike.md` (file of record; the packet-named
`B9-D2-SPIKE-notes.md` is the disclosed pointer):

- **Call counts vs caps**: creds check 1/1 (run FIRST, exit 0, output
  transcribed); DCR POSTs **1/2** (attempt 1 → 201; localhost control
  correctly NOT run — §4.2 makes it conditional on non-2xx); Query-API
  **0/2** (contingency never triggered); plus exactly ONE unauthenticated
  authorize-URL GET — sanctioned by §4.3(b) inside the ACCEPTED
  follow-through, `-o /dev/null -w`, no follow, claimed as well-formedness
  ONLY (the notes' claim discipline matches §4.3(b) verbatim). No other live
  traffic anywhere in B9 (R1/R2 harnesses are canned + local-CPython only).
  WITHIN BUDGET.
- **Raw curl (§4.1.5)**: honored — library never run live; `~/.mp/oauth/`
  mtime claim INDEPENDENTLY re-verified now: `client_us.json` mtime
  1784236054, still the only file — matches the notes byte-for-byte.
- **Redaction grep** (both repos, all B9 commits incl. throwaway/ and docs):
  zero `registration_access_token` values (the 201 body carried none — the
  packet's redact-to-8-chars rule had nothing to bite), zero JWT-shaped
  strings, zero `Bearer <secret>` material, zero `MP_SECRET`. The recorded
  `client_id` (`ClI8…XRvo`) is public RFC 7591 metadata with
  `token_endpoint_auth_method: none` — its recording is packet-MANDATED
  (§4.6 duty 2 residue table). The §3(a) authorize URL embeds a state +
  code_challenge from a throwaway local PKCE whose verifier is NOT recorded
  and was never used against `token/`. CLEAN.
- **Classification**: ACCEPTED criterion (attempt 1 → 2xx with client_id)
  matches the evidence; docs wording landed in README +
  `redirect-flow.ts` JSDoc is the §4.3 ACCEPTED row + §4.5 residual-gap
  triple verbatim, with the explicit no-e2e-claim sentence. §9 packet
  addendum matches the notes. Budget ledger, residue table, cleanup
  verification, and commit hashes all present.

## Findings

### F1 (MINOR, docs wording — packet-inherited): "verified in Phase-4 live burn-in" parses as a completed-verification claim
`packages/browser/README.md:23-24` + `redirect-flow.ts` JSDoc (and the §4.3
ACCEPTED row + §9 addendum they quote verbatim): "end-to-end browser
consent/exchange verified in Phase-4 live burn-in" is grammatically a
past-tense claim; the intent is future ("will be verified"). The builder is
citation-faithful — the packet mandates the label verbatim, and the very next
paragraph says "these docs claim no end-to-end verification", so no reader
can be actually misled. RECOMMENDATION to the arbiter: bless a one-word docs
tweak ("verified in" → "to be verified in") in the gate commit, or record the
wording as accepted-as-packeted. Non-blocking.

### O2 (observation, no action): Python's timeout + connection-error exchange rows merge into one transport-rejection re-take
`test_auth_flow.py:805` (`test_exchange_code_timeout`) and `:840`
(`test_exchange_code_connection_error`) are separate rows;
`redirect-flow.test.ts:365` covers both with one rejected-fetch test titled
"(timeout/connect twins)". In fetch semantics both twins are indistinguishable
rejections reaching the same catch in the hoisted core `postTokenRequest`,
and the translation-of-record (B8 node suites, untouched, 420/420 green)
retains the distinct rows against the SAME core body. No coverage lost.

### O3 (observation, no action): browser region twin asserts code only, not Python's `"uk" in str(exc)` message substring
`test_auth_flow.py:987` also asserts the region name appears in the message;
the browser re-take (`redirect-flow.test.ts:118`) asserts the code + the
zero-network invariant. R5 (codes-not-messages) is the standing posture for
authored/adapted suites, and the B8 node translation of the class is
untouched. Consistent with prior-batch precedent.

### O4 (observation, no action): browser `package.json` gains an `exports` field that core/node lack
Packet §2.5 says both "add `"exports": {".": "./src/index.ts"}`" and "match
whatever field set they use" — the two clauses conflict because core/node
carry NO exports field. Builder followed the explicit instruction and
DISCLOSED the reading in R1 notes ("the packet's explicit instruction to add
one to browser wins"). Inert for the repo (all imports are relative);
harmless.

## Dispatch checklist — final

- [x] 1. R10.2 diff for every translated test — PASS (1 minor-free; O2/O3 observations)
- [x] 2. Authored browser-contract tests cite their contract clause — PASS (10/10 files)
- [x] 3. Browser package purity + eslint boundary really covers packages/browser — PASS (R1-5 probe run both ways, reverted clean)
- [x] 4. Browser-bundle smoke genuinely builds browser+core — PASS (script inspected + probe-verified failure mode)
- [x] 5. Corpus still 3,251/0/0 — PASS (run at review time)
- [x] 6. Spike budget + redaction — PASS (1/2 DCR, 0/2 Query, sanctioned optional GET; zero token material in any committed artifact; mtime claim independently re-verified)

GO from lens 2. F1 goes to the arbiter as an optional gate-commit docs tweak.
