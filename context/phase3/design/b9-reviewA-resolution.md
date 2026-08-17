# B9 pair-A arbiter resolution (B9-ARB-A) — 2026-08-16

**Arbiter**: fable, ≤ high (P3-2 step d / b9-packets.md §6). Inputs: the two
pair-A reports (`b9-reviewA-semantics.md` @ Python `b542687`,
`b9-reviewA-assertions.md` @ Python `7237fdf`), `phase3-playbook.md` v1.1
(read fully), `b9-packets.md` (read fully, incl. the §9 spike addendum),
the B9 TS commits `9fcc489` / `009bad7` / `f6f298b`, and the live tree in
both repos. Every finding premise was independently re-verified against
source before ruling (citations inline below).

**Both reviewers' verdicts were GO with zero blocking findings.** Findings
arbitrated: 1 semantics minor (SEM-F1), 1 assertions minor (ASR-F1), 3
assertions no-action observations (ASR-O2/O3/O4).

## SEM-F1 — token_env refusal code (CONFIRMED → APPLIED, red-first)

**Claim re-verified**: `packages/browser/src/client.ts`
`staticTokenFromAccount` rejected a `token_env`-carrying `oauth_token`
account with `OAuthError("…", "OAUTH_CONFIG_ERROR", {field: "token_env"})`,
while the function's self-declared twin —
`OnDiskTokenResolver.get_static_token`, `token_resolver.py:273-282` —
raises `OAUTH_TOKEN_ERROR` with `details={"account_name", "env_var"}` for
the env-var-unusable condition (and `OAUTH_TOKEN_ERROR {account_name}` for
the `:267-272` model-invariant neither-field arm, which the browser arm
collapsed into the same single branch). CONFIRMED exactly as filed.

**Ruling: ALIGN to the Python twin** (the reviewer's second option), not
bless-the-narrowing. Reasons:

1. **A twin exists, so Python is the arbiter** (rulebook posture; ground
   state). The TS JSDoc itself names the function "the browser arm of
   `OnDiskTokenResolver.get_static_token`" — it cannot simultaneously claim
   the twin and diverge from the twin's coded failure surface. The R9.4
   narrowing is real, but it narrows the *precondition* (env is never
   readable in a browser), not the *condition class*: "static token
   unresolvable because the referenced env var is unusable" is the same
   condition on both runtimes, and consumers key on codes (R5).
2. **Cross-runtime consistency**: the node TS twin
   (`packages/node/src/auth/token-resolver.ts` `getStaticToken`) raises
   `OAUTH_TOKEN_ERROR {account_name, env_var}` for the identical account
   shape when the env var is unset — in a browser the env var is *always*
   unset. A hand-built session moved between the node and browser packages
   would otherwise flip codes for the same input.
3. **Package-internal consistency**: every other cannot-produce-a-bearer
   branch in `client.ts` (`readStoredTokens`: absent / non-JSON / expired)
   already uses `OAUTH_TOKEN_ERROR`; `OAUTH_CONFIG_ERROR` in the B9 surface
   otherwise means bad-region (`flow.py:164` twin) and
   localStorage-missing — genuine configuration-shape errors with no
   token-resolution semantics.
4. Core `OAuthTokenAccount` carries `token_env` (`account.ts:161`), so the
   Python-spelling details bag `{account_name, env_var}` (R7.6) is
   constructible with no type change.

The MESSAGE stays browser-explanatory (env reading is node-only, R9.4;
"pass an inline token") — message text is out of contract (R5.4).

**Applied red-first** (TS repo):

- RED: two new rows in `packages/browser/test/oauth-token-mode.test.ts`
  ("token_env account (hand-built session) refuses with the Python-coded
  OAUTH_TOKEN_ERROR {account_name, env_var}" + the model-invariant
  neither-field arm `{account_name}`), each asserting code AND details AND
  zero network captures. Confirmed failing against the shipped code
  (2 failed / 10 passed — both arms hit the old single
  `OAUTH_CONFIG_ERROR` branch).
- GREEN: `staticTokenFromAccount` rewritten as the two-branch twin of
  `token_resolver.py:250-282` / the node `getStaticToken` (token present →
  reveal; `token_env` present → `OAUTH_TOKEN_ERROR {account_name,
  env_var}` with the browser-specific message; neither →
  `OAUTH_TOKEN_ERROR {account_name}`, the explicit model-invariant raise).
  Suite green 12/12.
- **Ripples chased**: (a) `throwaway/b9-r1/edges.ts` "token_env in
  browser" expectation updated `OAUTH_CONFIG_ERROR` → `OAUTH_TOKEN_ERROR`
  with an inline arbiter cite; harness re-run with the RUN-record command
  (`npx vite-node throwaway/b9-r1/edges.ts`): **32 checks, 0 failures** —
  the recorded 32/0 reproduces. (b) `B9-R1-notes.md` arbiter addendum
  supersedes the RUN record's leg-1 `OAUTH_CONFIG_ERROR` line. (c) Grep for
  other locks on the arm: none in Layer-3 (the arm was throwaway-only —
  the two new tests close that gap); `credential-store.test.ts`'s
  localStorage-missing `OAUTH_CONFIG_ERROR` is a different, correctly-coded
  condition and is untouched. (d) The semantics report's suggested
  "bless in notes" alternative is superseded by this alignment; no
  narrowing entry is needed because no coded divergence remains.

## ASR-F1 — spike docs tense (CONFIRMED → APPLIED, docs-only)

**Claim re-verified**: `packages/browser/README.md` ("PKCE-in-browser
status") and the `redirect-flow.ts` module JSDoc carried the b9-packets.md
§4.3-ACCEPTED / §9 wording byte-for-byte: "end-to-end browser
consent/exchange verified in Phase-4 live burn-in" — grammatically a
completed-verification claim, while §4.5 mandates "The docs never claim
e2e verification under any outcome of this spike." The very next paragraph
at both sites does disclaim e2e verification (no reader is materially
misled; the builder was citation-faithful; the defect originates in the
packet wording).

**Ruling: APPLY the reviewer's one-word tweak now** (not deferred to the
gate): both sites now read "end-to-end browser consent/exchange **to be
verified** in Phase-4 live burn-in." Red-first is N/A — prose tense, no
assertable behavior; the substantive honesty lock is the adjacent
"these docs claim no end-to-end verification" paragraph, which is
unchanged (adding a grep test on sentence tense would be brittle prose-
pinning, unlike the packet-mandated security-warning grep which locks
REQUIRED content). Verified by grep before/after that these were the only
two sites carrying the phrase.

**Ripples chased**: the wording is packet-inherited, so a **§9 erratum**
was appended to `b9-packets.md` (this repo) directing the gate to consume
the corrected wording and not restore the §4.3-row spelling; the
`B9-spike.md` "docs wording as landed" transcription remains a historical
record of what the spike landed (accurate at its commit — not rewritten;
the erratum + this resolution are the pointers of record).

## ASR-O2 — timeout/connect row merge (CONFIRMED observation, NO ACTION)

Re-verified: Python `test_exchange_code_timeout` (:805) and
`test_exchange_code_connection_error` (:840) are distinct rows raising
distinct httpx exception classes; the browser re-take
(`redirect-flow.test.ts` "wraps a transport rejection in OAUTH_TOKEN_ERROR
(timeout/connect twins)") is one rejected-fetch test. In fetch semantics
both Python transports collapse to the same rejection path (fetch surfaces
one `TypeError` for both), and the translation-of-record — the B8 node
suites, byte-untouched, against the SAME hoisted `postTokenRequest` body —
retains both rows. No coverage lost; no change needed. The browser test is
a re-take of the wiring, not the translation of record (its own title
discloses the merge).

## ASR-O3 — region twin asserts code, not message substring (CONFIRMED observation, NO ACTION)

Re-verified: Python `test_invalid_region_raises_oauth_error` (:987-992)
asserts `code == "OAUTH_CONFIG_ERROR"` AND `"uk" in str(exc)`; the browser
twin (`redirect-flow.test.ts:117-134`) asserts the code plus
`transport.captures).toHaveLength(0)` — dropping the message substring per
the standing R5 codes-not-messages posture (prior-batch precedent; the B8
node translation of the class is untouched) while adding a strictly
stronger no-network-before-gate invariant Python never asserts. This is
the sanctioned R10.2 posture, not a weakening. No change.

## ASR-O4 — browser-only `exports` field (CONFIRMED observation → LEAVE AS-IS)

Re-verified: `packages/browser/package.json` carries
`"exports": {".": "./src/index.ts"}`; core and node carry none. The packet
§2.5 contained an internal conflict ("add exports" vs "match whatever
field set they use"); the builder disclosed the reconciliation in
`B9-R1-notes.md` (explicit instruction wins). **Ruling: leave as-is.** The
field is functionally inert today (every cross-package import in the repo
is a relative path), the explicit-instruction reading is the natural
resolution of the packet's own conflict, and retrofitting `exports` onto
core/node in the terminal batch is unforced churn with real-package
publishing decisions (entry-point maps, types conditions) that belong to
Phase-4 packaging. Recorded here so Phase-4 packaging starts from a known
asymmetry; no gate directive issued.

## Verification summary (post-application)

| Check | Result |
|---|---|
| `packages/browser` oauth-token-mode suite | 12/12 green (2 new rows, red-first verified) |
| `throwaway/b9-r1/edges.ts` re-run (RUN-record command) | 32 checks / 0 failures — reproduces |
| `npm run check` (TS, full: lint + typecheck + 9,936 tests + two-entry browser smoke) | GREEN, exit 0 |
| `npm run conformance` | **3,251 PASS / 0 FAIL / 0 UNPORTED @ 70c904dc — the terminal HOLD stands** |
| `just check` (Python repo — markdown-only changes this task) | GREEN, exit 0 (full recipe incl. the 3,251-vector Python-runner pass + build). Environment note: a first run under the agent harness's `FORCE_COLOR=3` showed 14 CLI-test failures from Rich emitting ANSI codes into captured output — a harness-env artifact, not a repo state; re-run with `env -u FORCE_COLOR -u COLORTERM` is the result of record |

**Applied-fix commit (TS `main`)**: `4b1884a` — "B9-ARB-A fixes
(b9-reviewA-resolution.md)": `client.ts` twin alignment + 2 Layer-3 rows +
docs tense fix ×2 sites + throwaway edge update (5 files, +104/−16).

## Verdicts (gate consumption)

| Finding | Verdict | Disposition |
|---|---|---|
| SEM-F1 (token_env error code) | CONFIRMED | APPLIED — aligned to Python twin `OAUTH_TOKEN_ERROR` + details, red-first, ripples chased |
| ASR-F1 (docs tense) | CONFIRMED | APPLIED — "to be verified in Phase-4 live burn-in" at both sites; packet §9 erratum appended |
| ASR-O2 (row merge) | CONFIRMED (observation) | NO ACTION — coverage retained in the node translation of record |
| ASR-O3 (code-only region assert) | CONFIRMED (observation) | NO ACTION — R5 posture; browser twin strictly stronger on the no-network axis |
| ASR-O4 (exports asymmetry) | CONFIRMED (observation) | LEAVE AS-IS — disclosed packet-conflict reading; Phase-4 packaging item |

**Pair-A GO stands. B9-R1 + B9-R2 + spike docs: GO from this arbiter**
(pair-B and its arbiter run independently per §6). No rulebook amendment
filed: no fix pattern recurred ≥3 times this batch (SEM-F1 is the first
browser-runtime code-choice divergence; the R11.9/R11.8 amendments already
cover the recurring classes seen in B7/B8). No bindings existed to check
(zero B9 vectors/api names — stated per §6 arbiter duty), and the §3.1
STOP-condition was not bypassed (both reviewers verified the hoist rows
byte-diff clean against their B8 homes; re-confirmed by spot-grep).

**HUMAN-CALL items: none new.** (The standing optional #9/#10
order-insensitive-comparison HUMAN-CALL remains open and non-blocking —
unchanged by this resolution.)
