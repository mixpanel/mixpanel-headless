# B7 pair-A arbiter resolution (task B7-ARB-A)

**Arbiter**: pair-A arbiter (fable, ≤ high), per `b7-packets.md` §5 and the
orchestrator's per-pair instantiation. **Date**: 2026-08-16.
**Inputs**: `b7-reviewA-semantics.md` (commit `c1bb05f`) +
`b7-reviewA-assertions.md` (commit `f6a8071`). Pair-B outputs NOT read
(blind-pair independence preserved; a separate arbiter pass covers them).
**Scope**: verify every pair-A finding against source, APPLY red-first or
REJECT with reason, chase ripples, rule on the two standing escalations both
reviewers queued.

**Fix commit (TS `main`)**: `4c8946a` — after it: `npm run check` green
(9,385 tests / 212 files, +17 over the shard baseline 9,368), lint boundary
green, `npm run conformance` re-verified **3,244 PASS / 0 FAIL / 7 UNPORTED**
@ `70c904dc` (unchanged — none of the fixes touch the probe binding path).
Python repo: this file + notes-file disclosure updates only (no Python
source touched; `just check` not required).

## Verdicts

| id | reviewer | severity | verdict | disposition |
|---|---|---|---|---|
| SEM-F1 | semantics | minor | **CONFIRMED** | **APPLIED red-first** (3 sites fixed + 5 spec-cited tests) |
| SEM-F2 | semantics | minor | **CONFIRMED** | **APPLIED red-first** (guard RESTORED via a new `TokenStore.accountDirExists` seam, not disclosure-only) |
| SEM-F3 | semantics | minor | **CONFIRMED** | **APPLIED** (JSDoc + notes disclosure; no code change) |
| SEM-N1 | semantics | nit | CONFIRMED | RECORDED only (R5.4 out-of-contract `null`-vs-`None` interpolations; unreachable with schema-valid `/me`) |
| SEM-N2 | semantics | nit | CONFIRMED | RECORDED — folded into ruling R2 (the Caution #13 ruling explicitly covers both sibling sites) |
| SEM-N3 | semantics | nit | CONFIRMED | **APPLIED** (comment corrected: UTF-16 code-unit order, coincident with codepoint order for all-ASCII digit IDs) |
| ASR-F1 | assertions | minor | **CONFIRMED** | **RATIFIED** (see below) |
| ASR-F2 | assertions | observation | CONFIRMED | no action (TestPublicSurface fold subsumes both originals) |
| ASR-F3 | assertions | minor | **CONFIRMED** | **APPLIED** (resolver-truth coverage PROMOTED to a permanent test) |
| ASR-F4 | assertions | observations | CONFIRMED | rulings R1/R2 below; item (c) recorded as a named B8-N2 re-take; item (d) verified intact |

## Applied fixes (all red-first where behavior changed)

### SEM-F1 — falsy-`or` param sites ported as nullish-`??` (3 sites)

Independently verified against source (`accounts.py:727/:997/:1812` vs the
TS twins) plus an arbiter-run live CPython probe for the third site:
`login_unified(token_env="")` with `MP_OAUTH_TOKEN` set raises
`ConfigError "--token-env '' is unset; cannot probe region."` — i.e. Python
falls back to `MP_OAUTH_TOKEN` at credential collection and rejects the
EMPTY `token_env` POINTER at the probe (`region_probe.py:252-256`), where
pre-fix TS errored immediately with `Env var '' is unset…`.

Red-first application: 5 spec-cited tests added FIRST (all red on the
pre-fix tree — verified), then the three sites converted to Python
falsiness (`x !== null && x !== ""`), each with a code comment citing this
file:

- `accounts-ops.ts` `accountsTest` — `test("")` → `account_name "(none)"`.
- `accounts-ops.ts` `accountsExportBridge` — `account: ""` falls through to
  the ACTIVE account (the materially divergent row: Python exports the
  active account, pre-fix TS raised `Account '' not found`); with no active
  account both languages raise `"No account specified and no active
  account configured."`.
- `login-unified.ts` `loginUnifiedNewCredential` — `token_env: ""` falls
  back to `"MP_OAUTH_TOKEN"` for the bearer READ while `resolvedTokenEnv`
  keeps Python's separate `is not None` check (so `""` still records the
  empty pointer downstream, exactly like `accounts.py:1819-1822`).

Ripple chase (arbiter, beyond the reviewer's three sites): full `' or '`
scan of `accounts.py` / `session.py` / `targets.py` / `naming.py`. All
other `or`-defaulting sites are on `account.default_project`, which the
Account model locks to `^\d+$` (`auth/account.py:114-117` — the empty
string is unrepresentable), so the TS `??` twins there
(`accounts-ops.ts:139`, `login-unified.ts:546`) are exactly equivalent.
`show()` uses `is None` (not `or`) — `show("")`/`test("")` correctly reach
`Account '' not found` in both languages. No further sites. Tests:
`accounts-namespace.test.ts` "B7-ARB-A SEM-F1 falsiness locks" (3),
`login-unified.test.ts` "B7-ARB-A resolution locks" (1 of 2).

### SEM-F2 — browser-flow orphan-directory guard silently dropped

Confirmed: `accounts.py:1704-1708` raises `ConfigError "Final account
directory … already exists. Run \`mp account remove …\` first or pass
--name."` for a per-account directory with NO config record; pre-fix TS
`writeTokens` silently overwrote. The reviewer offered disclosure-only as
the minimum; the arbiter rules for RESTORING the branch: it is observable
Python behavior (error vs silent repair) on a first-class flow, dropped
branches are the R10.8 founding failure mode, and the seam cost is one
interface member in the B7-defined (B8-implemented) `TokenStore`.

Applied red-first:
- `TokenStore.accountDirExists(name): boolean` added (`auth-effects.ts`) —
  JSDoc pins the B8 contract (`account_dir(name).exists()` on
  `~/.mp/accounts/{name}/`) and the in-memory dual (fake holds state for
  the name). `defaultAuthEffects()` stubs it with the standard
  `UNPORTED_AUTH_SEAM` thrower; the committed `UNPORTED_AUTH_SEAMS`
  constant already covers it via the `"tokenStore.*"` group entry —
  **B8-N2 must implement it** (outbound ledger addition below).
- Guard inserted in `loginUnifiedNewBrowser` AFTER the config-collision
  `AccountExistsError` and name-pattern checks, BEFORE `writeTokens` —
  the orphan state is left untouched (Python raises before the rename
  publishes; locked by the new test's identity assert).
- Disclosed residuals (extend shard-notes disclosure #2): (a) the TS
  message renders the NAME where Python renders the directory PATH (the
  in-memory seam has no path; message out of contract R5.4, class + code
  identical); (b) ORDERING nuance in the overlap state (config record AND
  dir both exist): TS raises `AccountExistsError` (config check first)
  where Python raises the dir-exists `ConfigError` — both refuse, class
  differs; this rides the already-header-cited placeholder-dir mechanism
  substitution.
- Test: `login-unified.test.ts` "browser flow refuses an ORPHANED
  per-account state…" (red pre-fix, green post-fix).

### SEM-F3 — `probeBaseUrl` origin-vs-urlunsplit skew undisclosed

Confirmed by code read (`region-probe.ts` `new URL(appUrl).origin` vs
Python `urlsplit`→`urlunsplit`): default ports dropped, userinfo dropped,
scheme/host lowercased on NON-canonical inputs; all in-repo call sites feed
the three canonical `ENDPOINTS` values, so unreachable via shipped
consumers but live on the exported function. Applied: JSDoc disclosure line
(citing this file) + disclosure appended to `B7-A2-notes.md`. No code
change (matches the reviewer's ask; the packet Caution #11 sanctioned the
`origin` mechanism).

### ASR-F3 — full-precedence-chain coverage was gate-deleted throwaway

Ruling: PROMOTE. Under the no-second-oracle posture (playbook Risk 7) the
batch must not lose its only randomized full-chain lock at gate cleanup.
Applied: `packages/core/test/auth/resolver-precedence-chain.pbt.test.ts`
(12 tests, permanent) — the exhaustive axis bitmaps (account 2^6, project
2^4 × 3 account states, workspace 2^5 through the full `resolveSession`),
the cross-axis rule locks the tables lean on (invalid-region abort,
empty-env fall-through, partial-quad ×4, SA-beats-OT, R11.7 grammar
acceptances, header-merge collision), and the 15-dimension `fc.record`
full-chain fuzz vs the independent `firstPresent` mini-model (seed
20260816, 600 runs — the harness RUN-record seed, reproduces
byte-identically). File header cites this ruling and states it is a
spec-cited ADDITION, not a Python translation (R10.2-safe). The gate task
still deletes `throwaway/b7-a2/` per §4.6 — nothing is lost now.

### ASR-F1 — TestSummaryTableDynamicWidth exclusion RATIFIED

The arbiter independently verified `test_accounts_namespace.py:967-991`
drives `cli.commands.account._format_summary_table` — a CLI renderer with
no library assertion to preserve; plan D4 defers the CLI. The exclusion is
**RATIFIED as an arbiter decision** (same standing as the packet-recorded
`TestCliExitCodes` exclusion, b7-packets.md §3.4). The test-file header
now cites this ratification. Ledger effect: `test_accounts_namespace.py`
62 Python tests → 60 translated + `TestPublicSurface` 2→1 fold + this
ratified exclusion — fully reconciled, zero silent drops.

## Rulings on the standing escalations

### R1 — Nd/Numeric_Type `MP_PROJECT_ID` guard-position split (A2 disclosure 1)

Both reviewers independently re-verified the disclosure against live
CPython (`"٤٢"` RESOLVES both languages; `"²"` raises ConfigError in both
— Python at the `Project(id=…)` model, TS at the env guard). **Ruling:
ACCEPTED as a disclosed message/details-only divergence.** Class + code
(`ConfigError` / `CONFIG_ERROR`) are identical — the R5 contract; messages
are out of contract (R5.4); a pinned `Numeric_Type=Digit` table (a
B0-1-style generated job) would buy byte-parity on an input class that is
unreachable from any recorded fixture, any Layer-3 assert, or any sane
environment, and is NOT commissioned. `TODO(port)` at the guard resolved
to a ruling-citing DISCLOSED-DIVERGENCE comment (R10.2 item-4 triage:
owner = this ruling). The A2 harness row locking class+code parity for
`"²"` stands; the fuzz-domain digit-string constraint (annotation-
constrained per Discrepancy #8 / user-ratification 1) already excludes the
class from randomized comparison — no comparison relaxation, no user
ratification required. Re-examine only if Phase-4 burn-in ever meets a
non-Nd Digit codepoint in a real `MP_PROJECT_ID`.

### R2 — Caution #13: `default_account_name` first-org insertion order

**Ruling: standing DISCLOSED DIVERGENCE per the Discrepancy #9/#10
mechanism** (option 1+2 of the packet's three; NOT the ordered-container
change — that would ripple an ordered-map value domain through the
B4-owned `MeResponse` shape for a divergence no recorded fixture can
produce). Python picks dict INSERTION order (`naming.py:122-124`); TS
`MeResponse.organizations` is a plain `Record` whose integer-like org-id
keys JS hoists ascending — the order is destroyed at `JSON.parse`/object
construction and is unrecoverable downstream. Divergence exists only when
`/me` emits organizations out of ascending-id order; every recorded
fixture and every Layer-3 fixture is ascending. The naming fuzz domain
stays ascending-id — a DOCUMENTED omission (no comparison relaxation ⇒ no
user ratification required, matching the #10 precedent). **The ruling
explicitly extends to the two sibling out-of-contract sites the semantics
review identified (N2)**: the "Accessible projects:" listing order inside
`_resolve_project`'s two error MESSAGES and picker-list tie order for
case-folded (org, name) key collisions — same mechanism, message-text /
degenerate-tie only; B8 and Phase-4 must not re-litigate them. `naming.ts`
JSDoc updated to cite this ruling.

**Playbook follow-through (outbound ledger `b7-packets.md` §7 row
"Caution #13 arbiter ruling follow-through")** — proposed discrepancy-log
entry, ready to paste at the B7 gate (kept out of the playbook here to
avoid write-collision with the blind pair's arbiter pass):

> 13. **First-organization pick + org/project listing order flip for
>     integer-like keys in `/me`-derived Records** (B7 pair-A arbiter
>     ruling R2, `b7-reviewA-resolution.md`, 2026-08-16). The #9/#10
>     JS-engine mechanism at three B7 sites: `defaultAccountName`'s
>     first-org pick (`naming.py:122` insertion order vs JS ascending
>     integer-key hoisting on `MeResponse.organizations`), the
>     "Accessible projects:" error-message listing order, and picker-list
>     tie order for case-folded key collisions. Divergent only when `/me`
>     emits orgs/projects out of ascending-id order (no recorded fixture
>     does); the first site can change the DERIVED ACCOUNT NAME, the
>     other two are message-text/degenerate-tie only. Naming fuzz domain
>     ascending-id (documented omission). Re-examine if Phase-4 burn-in
>     meets a live out-of-order `/me` or an ordered container ever enters
>     the `MeResponse` surface.

### R3 — `MP_WORKSPACE_ID` > 2^53−1 (A2 disclosure 2)

Already packet-pre-sanctioned (§2.2, Discrepancy #6/#7 family). No action;
recorded here for completeness.

## Ripples chased (beyond the findings)

1. `' or '` sweep over all four B7 Python modules — no falsy-`or` site
   beyond the three fixed (details under SEM-F1).
2. `TokenStore` interface growth: `fake-auth-effects.ts` extended
   (`accountDirExists` = held-state probe); tsc confirms no other
   implementor exists in-tree; `UNPORTED_AUTH_SEAMS` group entry
   `"tokenStore.*"` already covers the new member for B8.
3. `resolvedTokenEnv ?? "MP_OAUTH_TOKEN"` at the temp-account build
   (`login-unified.ts`) — verified UNREACHABLE-null by the same invariant
   as Python's `assert resolved_token_env is not None` (token===null ⇒
   resolvedTokenEnv!==null); `??` there is type-narrowing only, correct.
4. Conformance re-run post-fix: 3,244/0/7 unchanged (no probe-path
   contact). Full suite 9,385 green.

## Human calls (also surfaced to the orchestrator)

- **HUMAN-CALL (optional, non-blocking)**: Discrepancy #10's precedent
  offers the user an OPTIONAL order-insensitive-comparison ratification
  for #9/#10-mechanism sites. Ruling R2 uses the exclusion approach (no
  comparison logic changed), so no ratification is REQUIRED — flagging
  only because the first R2 site (derived account name) is
  RESULT-affecting, not message-only, if an out-of-ascending `/me` ever
  occurs live.

## Additions to the outbound (B8) ledger

- `TokenStore.accountDirExists(name)` — implement as
  `account_dir(name).exists()` (B8-N2), alongside the packet's existing
  `tokenStore.*` row.
- `test_session_to_credentials_oauth_browser_missing_tokens_raises` —
  named re-take with the real `OnDiskTokenResolver` (ASR-F4c; already
  covered by the §7 outbound row, now named).
- Gate task: paste discrepancy entry #13 (ruling R2 text above) into the
  playbook discrepancy log; the promoted
  `resolver-precedence-chain.pbt.test.ts` is PERMANENT — do not sweep it
  with the `throwaway/` cleanup.

## Gate posture

Pair-A verdict stands as reviewed: **GO** from both lenses, now with all
three MINOR + both nit-fix items applied and both escalations ruled.
Nothing in this resolution blocks the B7 gate; the flip spec (§4) is
unchanged.
