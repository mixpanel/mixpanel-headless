# B7 pair-B arbiter resolution (task B7-ARB-B)

**Arbiter**: pair-B arbiter (fable, ≤ high), per `b7-packets.md` §5 and the
orchestrator's per-pair instantiation. **Date**: 2026-08-16.
**Inputs**: `b7-reviewB-credentials.md` (commit `119f80a`) +
`b7-reviewB-e2e.md` (commit `336e47d`), reviewed against source in BOTH
repos. Unlike the reviewers, the arbiter also read the pair-A record
(`b7-reviewA-{semantics,assertions,resolution}.md`) — required for the
convergence note below; blindness bound the REVIEWERS, not the arbiter.
**Scope**: verify every pair-B finding against source, APPLY red-first or
REJECT with reason, chase ripples (including whether a fix invalidates
pair-A-verified state), and write the two-pair convergence record.

**Fix commit (TS `main`)**: `1151e86` — after it: `npm run check` green
(**9,386** tests / 212 files — the pair-A baseline 9,385 + the new
B-E2E-F1 lock), lint boundary green, `npm run conformance` re-verified
**3,244 PASS / 0 FAIL / 7 UNPORTED** @ `70c904dc` (unchanged — the only
`packages/*/src` edits are JSDoc; runtime behavior changes live in the
test-side fake + the new test).
**Python repo**: this file + the pair-B follow-up section appended to
`context/phase3/notes/B7-A1-notes.md` (docs only; no Python source
touched — `just check` not required, the pair-A-arbiter precedent).

## Verdicts

| id | reviewer | severity | verdict | disposition |
|---|---|---|---|---|
| CRED-F1 | credentials | minor (process) | **CONFIRMED** | **APPLIED** — reveal-site enumeration added to `B7-A1-notes.md` NOW (satisfying packet §3.3 literally, not deferred to the gate file); gate still folds it into `B7-notes.md` |
| CRED-F2 | credentials | minor (disclosure) | **CONFIRMED** | **APPLIED** — recorded as disclosure 13 in `B7-A1-notes.md`; NO code change (safe direction); gate carries it into `B7-notes.md` |
| CRED-F3 | credentials | minor (outbound caution) | **CONFIRMED** | **APPLIED** — SECRET SERIALIZATION RULE added to the `auth-effects.ts` module header where B8-N1 will read it; outbound-ledger row below (incl. the round-trip Layer-3 lock requirement) |
| B-E2E-F1 | e2e | minor | **CONFIRMED** | **APPLIED red-first, option (a)** — align to plain `ConfigError`, no discrepancy-log entry needed (see below) |
| B-E2E-N1 | e2e | test-infra note | **CONFIRMED** | **APPLIED (docs)** — `ConfigWrites` JSDoc layering correction + outbound-ledger row; fake promotion behavior KEPT (correct for the namespace transaction it models) |

All five verified against source; zero rejections. Both reviewers'
verdicts were GO and remain GO.

## Verification detail + applied fixes

### CRED-F1 — reveal-call enumeration missing from the shard notes

Arbiter re-ran the audit independently: `grep -rn "reveal()"
packages/core/src` yields exactly the 5 sites the reviewer lists
(`account.ts:585`, `region-probe.ts:382/:387`, `accounts-ops.ts:726`,
`login-unified.ts:593`); `grep get_secret_value()` over the six B7
Python modules yields exactly 4 (`region_probe.py:246/:250`,
`accounts.py:844/:1665`) — 1:1 with the Phase-2 `accountAuthHeader` as
the fifth TS twin. `B7-A1-notes.md` contained NO enumeration (grep for
`reveal|get_secret_value` → zero hits); the `accounts-ops.ts:15-21`
header carries a partial list that also names `token()` (a
plaintext-RETURN site, not a `reveal()` site — correctly distinguished).
**Applied**: the full table + the token()/fake-store distinctions now
live in `B7-A1-notes.md` ("Pair-B arbiter follow-up"). Improvement over
the reviewer's ask (gate-time fold into `B7-notes.md`): the packet says
"in the shard notes", so the shard notes now comply directly; the gate
fold still happens per §4.6.

### CRED-F2 — empty-Secret rendering divergence (safe direction)

Arbiter re-verified against live CPython/Pydantic:
`str(SecretStr(''))` → `''` AND `model_dump_json` → `""`, vs TS
`Secret.toString()/toJSON()` returning the fixed `'**********'`
unconditionally (`secret.ts:66-77`). The one B7 `new Secret("")` site
(`login-unified.ts:763`, `secret ?? new Secret("")`) is the SA-arm
defensive fallback — `detected_type === "service_account"` requires
`MP_USERNAME`+`MP_SECRET` present, so `secret` is non-null on every
reachable path. Strictly MORE redaction; not vector-observable; no
serialized bag is byte-diffed against Python output. **Applied** as
disclosure 13 in `B7-A1-notes.md` with the reviewer's re-examine
trigger. NOT promoted to a playbook discrepancy entry: the playbook log
records behavior a CONSUMER can hit meaningfully; this is a cosmetic
rendering of a value that never legitimately exists, below that bar —
the shard-notes disclosure (carried to `B7-notes.md`) is the right
altitude.

### CRED-F3 — Secret.toJSON() persistence foot-gun for B8 writers

Verified: `Secret.toJSON()` returns the mask; `AddAccountParams` /
`UpdateAccountFields` carry `Secret | string` fields and
`TokenStore.writeTokens` carries Secret-bearing `OAuthTokens` into
B8-owned effects; the fakes' `accountToRaw`/`toText`
(`fake-auth-effects.ts`) demonstrate reveal-at-write. The reviewer is
right that nothing STATED the rule for B8. **Applied**: the rule is now
in the `auth-effects.ts` module header (JSDoc — the interface B8-N1
implements), plus the outbound-ledger row below mandating a
write→read round-trip Layer-3 lock over a Secret-bearing account in B8.

### B-E2E-F1 — duplicate `accounts.add`: ACCOUNT_EXISTS vs CONFIG_ERROR

Verified end-to-end: Python `_apply_add_account` raises **plain
`ConfigError`** `"Account '{name}' already exists."` (`config.py:446`);
`AccountExistsError` appears in `accounts.py` ONLY at the login_unified
name-collision (`:1689`). Pre-fix TS: `fake-auth-effects.ts:165` threw
`AccountExistsError(name)` and the `ConfigWrites.addAccount` JSDoc
(`auth-effects.ts:138`) pinned that stronger class as the contract
B8-N1 would implement. R5 makes codes the contract → real divergence,
MINOR because `AccountExistsError extends ConfigError` preserves
class-family catches (both languages' Layer-3 assert only
`ConfigError`, verified: `test_accounts_namespace.py:166-177` /
`accounts-namespace.test.ts` both class-only).

**Ruling: option (a) — align, do NOT sanction.** The strengthening buys
nothing (the message is already identical, the code regresses parity)
and sanctioning it would hand B8 a discrepancy for free. Safety check
before applying: TS `loginUnified`'s own `AccountExistsError` at
`login-unified.ts:614` is thrown from its OWN `listAccounts()`
collision check, NOT recovered from `addAccount` — so the fake change
cannot break the login_unified path (and the SEM-F2 overlap-state
disclosure, which cites that same site, is untouched).

Applied red-first:
1. New lock `accounts-namespace.test.ts` "duplicate add surfaces plain
   CONFIG_ERROR, never ACCOUNT_EXISTS" (code `CONFIG_ERROR`,
   `constructor === ConfigError`, message byte-equal to Python) —
   **verified RED** on the pre-fix tree (failed at the code assert with
   `ACCOUNT_EXISTS`), green post-fix. Header-cites this resolution
   (spec-cited ADDITION, R10.2-safe — Python's own Layer-3 is
   class-only, so no Python assertion was altered).
2. `fake-auth-effects.ts` throw site → plain
   `ConfigError("Account '{name}' already exists.")` with a citing
   comment; the now-unused `AccountExistsError` import removed.
3. `auth-effects.ts:138` JSDoc corrected: plain ConfigError /
   CONFIG_ERROR, with the `accounts.py:1689` reservation named so
   B8-N1 implements the right class at each layer.

### B-E2E-N1 — FR-045 promotion layering attribution

Verified: `accounts.py:472-489` composes `_apply_add_account` +
first-account `_apply_set_active` inside ONE namespace-owned
`_mutate()`; `ConfigManager.add_account` itself does NOT promote.
The TS `ConfigWrites.addAccount` bundles the promotion — **KEPT**, and
correctly so: it preserves Python's one-transaction atomicity over a
seam bag whose members are each one transaction (packet §3.3 "never
two effect calls where Python makes one"); splitting promotion into a
second `setActive` effect call would introduce a crash window Python
does not have. What was wrong was the ATTRIBUTION (the JSDoc filed the
promotion under the `ConfigManager.add_account` seam name, inviting
B8-N1 to implement it inside the ConfigManager twin — where
`test_config.py`'s non-promoting asserts would then fail, or worse, be
"fixed"). **Applied (docs)**: the `ConfigWrites` doc block now states
the layering explicitly (promotion = the `accounts.add` namespace
transaction; implement ONCE in the B8 `ConfigWrites` adapter; keep the
underlying ConfigManager twin non-promoting with `test_config.py` as
that layer's lock) + the outbound-ledger row below. The fake's behavior
is unchanged (it models the adapter, which is the correct dual); the
reviewer's harness note (resolver fixtures seeding through the fake see
a non-empty `[active]`) is inherent to modeling the adapter and now
documented by the JSDoc.

## Ripples chased

1. **Grep for other ACCOUNT_EXISTS dependents**: `AccountExistsError`
   in TS src/tests appears only at `errors.ts` (definition),
   `login-unified.ts` (its own collision path — correct), the fake
   (fixed), and `errors.test.ts` (constructor unit — class still
   exists, correct). No other suite asserts the duplicate-add class
   beyond `instanceof ConfigError` (satisfied by both classes) — no
   collateral.
2. **Pair-A-verified state re-checked**: the SEM-F2 overlap-state
   disclosure ("TS raises AccountExistsError where Python raises the
   dir-exists ConfigError") cites `login-unified.ts:614`, untouched by
   this fix — disclosure stands verbatim. The SEM-F1 falsiness locks,
   the orphan-dir guard test, and the promoted
   `resolver-precedence-chain.pbt.test.ts` all re-ran green in the
   full-suite run (9,386/212). Pair-A's conformance claim re-verified
   at the post-fix tree: 3,244/0/7 @ `70c904dc`.
3. **Binding honesty spot-check** (P3-2d arbiter duty, P3-5 rule 3):
   `conformance-runner/src/wire-auth.ts` calls the REAL `probeRegion`
   with the REAL `probeClientFromFetch` over the harness fetch; no
   fetch issuance, error classification, or attempts assembly in the
   rig — honest. (Consistent with the credentials reviewer's
   honesty-adjacent check.)
4. **Harness RUN records**: both pair-B reviewers independently
   reproduced all four RUN records at the recorded seeds (352/72 +
   600@20260818; 788@20260816 + 660@20260817), and pair A did the same
   — four independent reproductions total; the arbiter accepts them
   without a fifth.
5. **The e2e reviewer's four "already sanctioned" adjudications**
   spot-verified against the record: WS1 mapping = packet §2.2 /
   Caution #14; >2^53 workspace = packet §2.2 + `B7-A2-notes.md`
   disclosure + pair-A ruling R3; Caution #13 org order = pair-A ruling
   R2 (the e2e reproduction exactly matches the ruled behavior);
   unmapped-cause fallback = Caution #8's disclosed best-effort. All
   four correctly scoped — no re-litigation.

## Two-pair convergence note (the doubled-review justification record)

**Classes BOTH pairs hit independently** (highest-confidence findings
of the batch — pair B had no access to pair-A output, so agreement is
evidence, not echo):

- **Caution #13 / org-order integer-key hoisting**: pair A escalated
  and got ruling R2; pair B's e2e sweep independently constructed the
  out-of-ascending `/me` scenario and reproduced the divergence
  byte-for-byte as ruled (incl. the non-integer-key MATCH control).
  Also independently flagged by both as Phase-4-reachable via derived
  naming.
- **`MP_WORKSPACE_ID` > 2^53−1 coded-ConfigError mapping**: pair-A
  ruling R3 (packet-pre-sanctioned); pair-B e2e row R33 hit it blind
  and traced it to the same packet §2.2 sanction + notes disclosure.
- **Nd-digit env-value handling**: pair-A ruling R1 (guard-position
  split, `"٤٢"` resolves both sides); pair-B drove Nd rows through
  both `MP_PROJECT_ID` and `MP_WORKSPACE_ID` blind and confirmed
  observable parity.
- **Network-error reverse-table rendering (Caution #8)**: pair A
  verified 23 paired probe scenario groups; pair B independently
  verified `ConnectError` AND `ConnectTimeout` rows byte-identical
  end-to-end and confirmed the unmapped-cause fallback scope.
- **The 14-vector replay + all RUN-record seed reproductions**: done
  independently by both pairs (3,244/0/7 pre-flip both times).
- **Post-arbiter falsiness behavior** (`accounts.test("")` →
  `"(none)"` etc.): pair-A originated the finding (SEM-F1); pair B,
  reviewing the post-fix state blind, independently verified the fixed
  behavior equals live Python — convergent verification of the fix
  itself.

**Pair-B-only finds** (what a single review pair would have missed —
the record justifying P3-3 doubling on the no-second-oracle batch):

- **B-E2E-F1** (the only code-behavior defect either pair found in
  this pass): the duplicate-add error-CLASS divergence lived in the
  seam CONTRACT (interface JSDoc + fake), not in any Python-range
  line-by-line diff — pair A's semantics lens diffs implementation
  against Python ranges and structurally could not see it; only
  cross-language END-TO-END execution of the same operation surfaced
  the code mismatch. Left unfixed it would have been baked into
  B8-N1's real ConfigManager adapter.
- **B-E2E-N1**: the promotion-layering attribution error — same
  mechanism (contract-vs-source, not implementation-vs-source), same
  reason pair A could not see it; it was a wrong-layer implementation
  trap aimed directly at B8-N1.
- **CRED-F1/F2/F3**: the reveal-site 1:1 audit gap, the empty-Secret
  cosmetic divergence, and the B8 JSON-persistence foot-gun — all
  products of the credential-safety lens (adversarial serialization
  probes, allowlist diffing) that pair A's semantics/fidelity lenses
  do not run. F3 in particular is a forward-defect preventer: the
  first pair's process could not have generated it.

Net: pair B found zero contradictions with pair-A-verified state (the
doubling also functioned as an independent CONFIRMATION pass over the
pair-A fixes at `4c8946a`), and contributed one real code-contract fix
plus three B8-defect preventers that single review would have missed.

## Additions to the outbound (B8) ledger

- **Secret serialization rule (CRED-F3)**: every B8 on-disk credential
  writer (`ConfigWrites` members taking `AddAccountParams` /
  `UpdateAccountFields`, `TokenStore.writeTokens`, `BridgeEffects.export`)
  calls `reveal()` at its designated write site; a `Secret` routed
  through `JSON.stringify`/generic serialization persists the literal
  mask (silent credential corruption). B8 adds a Layer-3 write→read
  round-trip lock over a Secret-bearing account (SA secret + OT token
  + OAuthTokens). Rule text lives in the `auth-effects.ts` header.
- **FR-045 promotion layering (B-E2E-N1)**: implement the first-account
  promotion exactly ONCE — in the B8 `ConfigWrites.addAccount` adapter
  transaction — and keep the ported `ConfigManager.add_account` twin
  non-promoting; translate `test_config.py`'s non-promoting
  `add_account` asserts against the ConfigManager layer as the lock.
- **Duplicate-name error class (B-E2E-F1)**: B8's real
  `ConfigWrites.addAccount` raises PLAIN `ConfigError` / CONFIG_ERROR
  for duplicates (`config.py:446` parity — the corrected JSDoc + the
  committed `accounts-namespace.test.ts` lock are the contract);
  `AccountExistsError` stays exclusive to the login_unified collision
  path.
- **Gate task (B7)**: when folding shard notes into `B7-notes.md`,
  carry the reveal-site enumeration and disclosure 13 (CRED-F2) from
  `B7-A1-notes.md`'s pair-B follow-up section.

## Human calls

None required by this resolution. For completeness:

- **HUMAN-CALL (none new)**: B-E2E-F1 was resolved by ALIGNMENT (option
  a), so no sanctioned-deviation entry and no ratification is needed;
  CRED-F2 stays a shard-notes disclosure (safe-direction cosmetic), not
  a playbook discrepancy. The only open optional item remains pair A's
  HUMAN-CALL on the Caution #13 order-insensitive-comparison
  ratification (`b7-reviewA-resolution.md`) — pair B's independent
  reproduction of that divergence, including its Phase-4 reachability
  note, mildly STRENGTHENS the case for the user taking that optional
  look, but changes nothing about its non-blocking status.

## Gate posture

Pair-B verdict stands as reviewed: **GO from both lenses**, now with
all five items applied (1 red-first code fix, 2 documentation-contract
corrections, 2 notes/disclosure records). Combined two-pair posture:
GO — nothing in either resolution blocks the B7 gate; the flip spec
(§4) is unchanged; the gate inherits three duties from this file
(B7-notes fold-ins ×2, discrepancy-#13 paste from pair A).
