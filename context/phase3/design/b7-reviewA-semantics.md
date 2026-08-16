# B7 adversarial review — Pair A, Lens 1: resolver/probe semantics

**Reviewer**: pair-A lens-1 (resolver/probe semantics), per `b7-packets.md` §5
and the orchestrator's batch-level doubling ruling (each pair reviews BOTH
shards). **Scope**: all B7 commits — TS `64542e1` (B7-A2) + `e34d218` (B7-A1)
since the B7-DL commit `f492a4e`; Python notes commits `04e2f23` / `b8baee5`.
**Date**: 2026-08-16. **Verdict: GO** — zero blocking findings; 3 MINOR
findings + 3 nits below, all edge-path or disclosure-gap; the core precedence,
probe, and namespace semantics verified byte-for-byte against Python.

Per-shard coverage under this lens: **A2** (resolver core, region probe,
binding, edge tests) — items 1–6 below; **A1** (accounts/session/targets
namespaces, login_unified, naming, ResolverSeams) — items 7–12. Findings F1–F3
are A1; N1–N3 span both.

---

## 1. Independent cross-language truth table (A2 resolver) — 233,280 rows, ZERO divergences

I did NOT rely on the shard's own `throwaway/b7-a2/resolver-truth.ts`
mini-model. I built a fresh cross-language harness:

- **Python side**: the REAL `resolve_session` over a real tmp-dir
  `ConfigManager` (16 config variants: `[active].account` × `[active].workspace`
  × `acct.default_project` × `[settings].custom_header`), a real `BridgeFile`
  (3 variants: none / full-with-project+workspace+colliding-headers / minimal),
  real `os.environ` mutation (6 vars × {absent, empty, set} where meaningful:
  3·2·3·3·3·3 = 486 env combos), and 10 param combos (2×2×2 axis kwargs +
  `target=tgt_full` + `target=tgt_min`). 16 × 3 × 486 × 10 = **233,280 rows**,
  each canonicalized to (account type/name/region/username, project id,
  workspace id, sorted headers) or (exception class, exact message).
- **TS side**: the REAL `resolveSession` over injected `ResolverSources`
  fixtures mirroring the same enumeration, diffed row-by-row against the
  Python JSONL (`ParamValidationError`/`WS1_TARGET_MUTUALLY_EXCLUSIVE` mapped
  to Python's bare `ValueError` per packet Caution #14; messages compared
  EXACTLY, not just classes).

**Result: 233,280 / 233,280 identical** — including FR-024 error texts, the
region-abort position (invalid `MP_REGION` raising even when a lower-rung
winner exists), SA-quad-over-OT, partial-quad silent fall-through, empty-string
env absence on every var, header merge order (settings first, bridge wins on
`X-C` collision), the no-`[active].project` rung (FR-033), and the `null`
workspace terminal.

Targeted error rows (25) on top of the product: invalid `MP_REGION`
(alone / with `account=` param / with full quad), `MP_PROJECT_ID`
`12x`/`+42`/`4_2`/`" 42"`/Nd `"٤٢"`/No `"²"`, `MP_WORKSPACE_ID`
`abc`/`0`/`-3`/`1_0`/`" 42 "`/`18.0`/`"٤٢"`/`9007199254740993`, explicit
workspace `0`/`-5`/`1.5`, explicit project `12x`/`""`, unknown account/target,
target+axis guard. **23/25 exact-match incl. messages**; the 2 mismatches are
EXACTLY the two divergences the shard disclosed and escalated (see §5) —
nothing undisclosed.

## 2. Probe branch pairing (A2) — 23 scenario groups, byte-identical

Fresh paired harness: Python `probe_region` with duck-typed fake clients
raising real `httpx.ConnectError`/`ConnectTimeout` vs TS `probeRegion` with
fake `ProbeClient`s rejecting `MixpanelHttpError` carrying the
`cause.code` chain. Compared: result region, attempts arrays (2-tuple success
mirroring with bodies dropped; 3-tuple failures with bodies), error class +
message + `attempts` payload, the **full get/close call log** (order,
headers-forwarded-verbatim, `/api/app/me` path, per-request `timeoutSeconds`),
and factory invocation sequences.

Groups: success at position 1/2/3; 401/403/500 flow-through (no per-status
branching); net-then-ok and timeout-then-ok (`ConnectError: DNS lookup failed`
/ `ConnectTimeout: timed out` rendering via the Caution-#8 reverse table);
all-401 → `RegionProbeError`; all-net → `RegionProbeNetworkError`; both mixed
arrangements → generic; custom order `["eu","us"]`; single `["eu"]`; **empty
`[]` → network subclass with `attempts: []`** (the `all([])` edge); duplicate
`["us","us"]` (factory called twice); body cap at 4095/4096/4097/4098 and a
surrogate-pair straddle at the 4096 cut (cpSlice — no split surrogate);
empty headers; timeout plumb 2.5. **All 23 groups byte-identical**, including
close-in-finally on the 200 path (close event precedes return in the log) and
on the network-continue path.

`probeRegionForCredential`: branch order verified against
`region_probe.py:241-287` line-by-line — SA missing-material ConfigError, UTF-8
base64 via the ONE exported `base64EncodeUtf8` (R10.8), inline token > token_env,
`getEnv` unset/empty → ConfigError (`if not bearer` twin), non-probeable type
ConfigError, narrate messages verbatim (incl. ✓/✗ markers), default
order/timeout used exactly as Python's bare `probe_region(_factory, headers)`.
`ENDPOINTS` table verified identical to `api_client.py:153-172`.

## 3. Binding honesty + conformance replay (A2)

`conformance-runner/src/wire-auth.ts` calls the REAL `probeRegion` with the
REAL `probeClientFromFetch` over the harness fetch; the `client_factory`
callback stub only logs the region; no self-issued fetches, no
self-classification, no self-assembled attempts; absent kwargs omitted so
library defaults apply; NO batch-status flip in the module commits (gate duty
preserved — `region_probe.` still pending). Independently replayed:
`npm run conformance` → **3,251 — 3,244 PASS / 0 FAIL / 7 UNPORTED** at pin
`70c904dc598d` (the §2.8 pre-flip checkpoint; +14 passing-while-pending; the 7
remaining are `oauth_flow.refresh_tokens`).

## 4. Harness + Layer-3 reproduction

- `throwaway/b7-a2/{resolver-truth,probe-branches}.ts` re-run from recorded
  seeds 20260816/20260817: 788 + 660 checks, 0 failures, 0 fuzz divergences —
  matches the RUN record.
- `throwaway/b7-a1/{namespace-branches,ops-fuzz}.ts` re-run (seed 20260818):
  352 checks / 0 failures / 72 captured errors; 600 sequences / 3,676 ops /
  0 divergences — matches.
- Layer-3: `packages/core/test/auth` + `test/accounts` (18 files, 272 tests)
  and `test/workspace` + `me-service` + `client-workspace` (47 files, 1,541
  tests) all green.
- Lint boundary: eslint green over the new files; grep for
  `process.env` / `node:` imports in `core/src/auth` + `core/src/accounts`
  finds doc-comments only (R9.1/R9.4 clean).

## 5. The two disclosed A2 divergences — VERIFIED as disclosed, correctly escalated

1. **No-digit (`Numeric_Type=Digit` outside Nd, e.g. `"²"`) `MP_PROJECT_ID`**:
   I verified live (uv CPython): `"²".isdigit()` is True; Python passes the
   guard and fails at `Project(id=...)` → `ConfigError "Invalid project ID:
   '²'. …"`. TS `/^\p{Nd}+$/u` fails at the GUARD → `ConfigError
   "MP_PROJECT_ID='²' must be a digit string."` (same class/code; different
   message + details). Also verified the shard's packet CORRECTION: Nd digits
   (`"٤٢"`) resolve successfully in BOTH languages (pydantic-core's Rust `\d`
   is Unicode Nd; `parseProject`'s `PROJECT_ID_PATTERN` is `/^\p{Nd}+$/u` to
   match) — the packet §2.2's claimed Nd two-stage failure does NOT exist; the
   implementer's live-probe override is correct and properly escalated to the
   arbiter in `B7-A2-notes.md`. Endorsed: accept class-level parity (byte
   parity needs a pinned Numeric_Type table; arbiter's call).
2. **`MP_WORKSPACE_ID` > 2^53−1**: Python parses and USES
   `9007199254740993`; TS raises the coded ConfigError per the packet's
   pre-sanction (Discrepancy #6/#7 family). Verified live both sides.

## 6. FINDINGS

### F1 (MINOR, A1, correctness-edge) — Python falsy-`or` sites ported as nullish-`??`: empty-string arguments diverge

Three sites use `??`/`=== undefined` where Python uses truthiness on a
PARAMETER (not env), so `""` takes the wrong branch. Live-verified evidence
for the first two:

| Site | Python (verified) | TS (verified) |
|---|---|---|
| `accounts.test("")` — `accounts.py:729` `name or "(none)"` vs `accounts-ops.ts:610` `name ?? "(none)"` | `account_name == "(none)"` | `account_name == ""` |
| `accounts.export_bridge(account="")` — `accounts.py:1000` `account or cm.get_active().account` vs `accounts-ops.ts:830` `options.account ?? …` | falls through to the ACTIVE account (or "No account specified and no active account configured.") | uses `""` literally → `Account '' not found.` — with an active account configured Python EXPORTS THE ACTIVE ACCOUNT while TS errors |
| `login_unified(token_env="")` new-credential path — `accounts.py:1821` `token_env or "MP_OAUTH_TOKEN"` vs `login-unified.ts:696` `args.token_env ?? "MP_OAUTH_TOKEN"` | reads `MP_OAUTH_TOKEN` (then fails later at persist/probe with a different message) | errors immediately `Env var '' is unset…` (code-read; same mechanism as the two verified twins) |

No corpus vectors and no Layer-3 rows exercise `""` params, so nothing is red.
This is watchlist-#6's dual (there the rule is "explicit `undefined`/`""`
checks for ENV"; on Python-`or` PARAM sites the faithful port is
`(x ?? null) === null || x === ""`-style falsiness, per site). Recommend:
arbiter directs a red-first fix of the three sites (or an explicit
disclosed-divergence ruling; the export_bridge row is the only one with a
materially different outcome under a realistic config).

### F2 (MINOR, A1, disclosure-gap) — browser-flow "final account directory already exists" guard dropped without a disclosure line

Python `_login_unified_new_browser` raises `ConfigError "Final account
directory {dir} already exists. Run `mp account remove {name}` first or pass
--name."` when an ORPHANED per-account dir exists without a config record
(`accounts.py:1706-1711`). The TS flow (`login-unified.ts:628`) has no
equivalent: `tokenStore.writeTokens` silently overwrites and the flow
proceeds (the `AccountExistsError` collision check only covers names present
in CONFIG). Disclosure #2 in `B7-A1-notes.md` covers the placeholder-dir →
in-memory substitution and claims "observable contract identical", but this
branch is an observable difference (error vs silent repair) not mentioned
there. Recommend: add the branch to disclosure #2 (either as an accepted
divergence — arguably TS-better behavior — or push an existence probe into the
`TokenStore` contract for B8); arbiter's call. No test impact (no Layer-3 row
drives the orphan state).

### F3 (MINOR, A2, disclosure-gap) — `probeBaseUrl` origin-vs-urlunsplit skew undisclosed

`probeBaseUrl` uses `new URL(appUrl).origin` (packet Caution #11 sanctions
this). Verified skew vs Python `urlsplit→urlunsplit` for NON-canonical inputs:
`https://host:443/x` → Python `https://host:443` / TS `https://host` (default
port dropped); `https://user:pass@host/x` → Python keeps userinfo / TS drops;
`HTTPS://MixPanel.COM/x` → Python preserves case / TS lowercases. All
in-repo call sites feed only the three canonical `ENDPOINTS` values (verified
identical), and the harness's 6 URL shapes + the Layer-3 shapes are all in the
agreeing region — so this is unreachable via shipped consumers but LIVE on the
exported public function. The A2 RUN-record disclosure list does not mention
it (the packet's "equivalent for http(s)" claim is only true for canonical
URLs). Recommend: one JSDoc/RUN-record disclosure line; no code change needed.

### N1 (nit) — `None` vs `null` in out-of-contract message interpolations

`login-unified.ts:480` relogin narrate renders `(currently null)` where Python
prints `(currently None)`; the E-2 message renders a `null` project name as
`null` vs Python `None` (`accounts-ops.ts:243`). Both texts are R5.4
out-of-contract narration/messages and unreachable with schema-valid `/me`
payloads; record only.

### N2 (nit) — Record-iteration order at message/tie sites (Caution #13's mechanism at two more OUT-OF-CONTRACT sites)

The Caution #13 escalation (first-org pick in `defaultAccountName` — properly
disclosed, NOT self-sanctioned, awaiting arbiter) is handled correctly. The
same integer-key-hoisting mechanism also affects (a) the "Accessible
projects:" listing ORDER in `_resolve_project`'s two error messages
(`login-unified.ts:156-198` iterates `Object.keys` = ascending-numeric vs
Python insertion order) and (b) picker-list tie order when two projects share
a case-folded (org, name) key (V8 stable sort over hoisted entries vs Python
stable sort over insertion order). Both are message-text / degenerate-tie
only; suggest the Caution-#13 arbiter ruling note them as covered by the same
mechanism so B8/Phase-4 don't rediscover them.

### N3 (nit) — comment accuracy in `accountsLogin`

`accounts-ops.ts:741-743` labels `[...projectKeys].sort()` a "codepoint sort";
default `Array.sort` is UTF-16 code-unit order. Equivalent to Python's
codepoint `sorted()` for the digit-string project IDs that reach it (and
`login-unified.ts` correctly uses `compareCodepoints` where it matters), but
the comment overclaims; fix the comment or switch to `compareCodepoints` for
uniformity.

## 7. Namespace surfaces (A1) — verified against `session.py` / `targets.py` / `accounts.py`

- `session-namespace.ts` — guard text + code (`WS1_TARGET_MUTUALLY_EXCLUSIVE`
  reuse per Caution #14), ONE `applySession`/`applyTarget` transaction per
  call, `show()` passthrough: line-equivalent to `session.py:24-77`. ✓
- `targets-namespace.ts` — 5 members map 1:1 onto the `ConfigWrites` seam;
  ordering/duplicate/referential semantics correctly live on the B8-owned
  `ConfigManager` twin and are pinned in the interface JSDoc with config.py
  line cites. ✓
- `accounts` namespace — 13 `__all__` names present; camelCase method /
  Python-spelled options-bag keys decision recorded (notes #7). `use()`
  clears the workspace pin in ONE transaction via `SetActiveUpdate`
  (`workspace: null` ⇒ clear — a deliberate, documented semantic shift from
  Python's `set_active(workspace=None)`="untouched"; the fake implements it
  and B8 consumes the interface by name). `show`/`test`/`login`/`logout`/
  `token`/`update`/`remove` branch orders, messages, and error classes
  verified line-by-line (incl. `test()`'s never-raise contract, the E-2
  atomic-publish ordering in `login()` — probe on the in-memory bearer,
  persist only after the cross-check, `default_project` backfill only when
  changed — and `token()`'s per-request resolution through the injected
  `TokenResolver`, R2.9). `slugify` paired against CPython over 416
  ASCII/Latin-1/ligature/astral cases: 0 diffs; `defaultAccountName`
  suffix-at-2 semantics identical.
- `login_unified` — flag-fold → detect → misuse-guards → relogin/new dispatch
  → `use(summary.name)` activation: order identical to
  `accounts.py:1165-1272`. Detection priority (explicit > token_env >
  SA-env-pair > OT-env > browser) with empty-env-as-absent verified.
  Relogin E-3/E-4 refusals, the token_env mode-preservation matrix
  (explicit pointer / preserved pointer / inline rotation), SA env+stdin
  collection, `/me`-refresh + meCache write on EVERY relogin arm, and the
  credential flow's probe-only-when-region-omitted all match. `_resolve_project`
  chain (explicit → env hard-fail-if-stale → single → zero→null → picker with
  (org,name) case-folded codepoint sort incl. the `~org {id}` sink) matches;
  `ProjectNotFoundError(project, available_projects)` and
  `InvalidArgumentError` details (`violation`, `detected_auth_type` — key
  spelling verified in `errors.ts:517-520`) match Python.

## 8. ResolverSeams ownership split (A1) — matches packet §3.2 exactly

- 4 of 5 W1-D1 seams REAL in `resolver-seams.ts` (`resolveSession({target})`
  over `resolverSourcesFromEffects` with bridge loaded AT CALL TIME —
  faithful to Python's per-resolution `load_bridge()`; `getAccount`;
  `resolveProjectAxis` over `effects.env` + call-time bridge;
  `envWorkspaceId`). `persistActive` ROUTED to `effects.persistActive`
  (default throws `UNPORTED_AUTH_SEAM`) with the real composition shipped as
  `persistActiveToConfig` — verified equivalent to `workspace.py:696-722`
  (`clear_workspace` exactly when the in-session workspace is null).
- `UNPORTED_AUTH_SEAMS` matches the packet's verbatim list + the two
  DISCLOSED additions (`readSecretStdin` stubbed; `narrate` no-op, correctly
  excluded from the list). `defaultAuthEffects` throws coded
  `UNPORTED_AUTH_SEAM {seam}` on every B8-owned member incl. per-var env
  getters; `fetchImpl`/`now` ambient per packet ("CORE, no stub").
- Workspace constructor: WS1 guard fires FIRST and unconditionally (matches
  `workspace.py:455-465` — before the session-bypass branch); resolver path
  requires injected `sources` with a coded `UNPORTED_AUTH_SEAM
  {seam:"workspaceSources"}` (disclosure #11); bridge-token materialization
  correctly left to B8 (`TestBridgeTokenMaterialization` header row kept).
  Note for B8 (already covered by the notes' by-name deferral, recorded here
  for the arbiter): `ConfigWrites.addAccount` carries the FR-045
  first-account promotion that in Python lives in `accounts.add`'s
  `_mutate()` composition, NOT in `ConfigManager.add_account` — B8 must
  implement the INTERFACE contract, not a verbatim `config.py` port, for
  this member (JSDoc cites `accounts.py:472-489`).

## 9. Standard P3-2(d) items under this lens

- R10.2 weakening diff over the semantics-bearing suites: the header-cited
  substitutions in `resolver.test.ts` / `resolver.pbt.test.ts` /
  `region-probe.test.ts` / `account-edge.test.ts` / `session-replace*.ts`
  (env-bag for monkeypatch, injected fn for the probe spy, spread for
  `model_copy`, no-source-mutation for `TestNoSideEffects`) all cite packet
  §2.2/§2.4 and none weaken an assertion I could detect against the Python
  originals. (Full test-count reconciliation is lens-2's ledger.)
- GATE-R5: probe bodies are opaque captured text (never parsed) — no
  `JSON.parse` on wire bodies added; `fetchMe` routes through
  `toNativeJson` on the client's lossless output. ✓
- `TODO(port)` triage: 3 new markers, all legitimate B8/arbiter pointers
  (resolver Nd guard, workspaceSources, unportedAuthSeam docs). ✓
- Codes-not-messages: no new codes minted; `WS1_TARGET_MUTUALLY_EXCLUSIVE`
  reused at all three guards; `ParamTypeError` for the Python `TypeError`
  twins (R5.5). ✓
- Watchlist #13: no new `isinstance(x, dict)`-family local guards in the B7
  ranges (the `/me` payload path reuses the model parse boundary). ✓

## 10. Disposition summary for the arbiter

| id | severity | shard | disposition sought |
|---|---|---|---|
| F1 | MINOR | A1 | fix 3 falsy-`or` sites red-first, or rule a disclosed divergence (export_bridge row is the substantive one) |
| F2 | MINOR | A1 | extend disclosure #2 (orphan-dir branch) or add a B8 `TokenStore` existence-probe note |
| F3 | MINOR | A2 | one disclosure line for the `probeBaseUrl` origin skew |
| N1–N3 | nit | both | record; optional comment fix (N3) |
| Caution #13 escalation | — | A1 | endorse: rule per #9/#10 options; extend the ruling to cover N2's two sibling sites |
| Nd/No isdigit escalation | — | A2 | endorse: accept class-level parity (byte parity needs a pinned Numeric_Type table) |
| >2^53 workspace mapping | — | A2 | already packet-sanctioned; no action |

Evidence artifacts (throwaway, deleted after this review; scripts described
inline above): 233,280-row resolver truth table, 25 targeted error rows, 23
probe scenario groups, 416 slugify pairs, live falsiness probes, conformance
replay 3,244/0/7, harness seed reproductions, scoped eslint run.
