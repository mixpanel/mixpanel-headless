# B7 review — Pair B (BLIND), Lens 2: adversarial end-to-end auth scenarios

**Status**: complete · 2026-08-16 · fable, ≤ high effort.
**Blindness attestation**: no `b7-reviewA-*` file, no reviewA resolution, and
no shard-notes review section was read. Inputs: Python sources at HEAD
(`ts-port/phase2-contract-support`, corpus pin `70c904dc`), the TS diff
(`db8e079..4c8946a`: B7-A2 `64542e1`, B7-A1 `e34d218`, arbiter-fix `4c8946a`
— reviewed at the POST-arbiter state per the orchestrator ruling), the B7
packet (`b7-packets.md`), and the playbook v1.1. Per-shard coverage: this
lens drove BOTH shards end-to-end (A2: resolver + region probe + cred
probe; A1: accounts/session/targets namespaces + login_unified + naming).

## Method

77 paired end-to-end scenarios were constructed across account types
(service_account / oauth_browser / oauth_token) × precedence sources
(env / explicit param / target / bridge / `[active]` config) × region and
probe outcomes (200-at-each-position / HTTP-fail / network-fail / mixed /
empty-order), and executed against BOTH implementations through the REAL
public surfaces with injected fixtures:

- **Python**: scratch driver (`/tmp/b7e2e/py_scenarios.py`, `py_round2.py`
  + two inline rounds) — real `resolve_session` over a tmp-file
  `ConfigManager` + real `BridgeFile`, real `probe_region` over duck-typed
  clients raising real `httpx` errors, real `probe_region_for_credential`
  with the module's `httpx` binding shimmed to a capture client, real
  `accounts`/`session`/`targets` namespaces over `MP_CONFIG_PATH`/`HOME`
  tmp dirs, real `login_unified` with `MixpanelAPIClient.me` stubbed
  (the upstream suite's own pattern).
- **TS**: vitest scratch (4 files, run then DELETED — tree left clean) —
  real `resolveSession` over `ResolverSources` bags (committed
  `fake-auth-effects.ts` config fake + literal env bags + `BridgeView`s),
  real `probeRegion` through REAL `probeClientFromFetch` over injected
  fetches (network failures shaped exactly like the conformance harness:
  `TypeError("fetch failed", {cause: Error{code}})`), real
  `probeRegionForCredential` with a fetch spy, real namespace factories
  over `makeEffects()`, real `loginUnified` with `meFetch`.

Outcomes were normalized to a shared JSON shape (session: account fields
with secrets revealed for equality, project id, workspace id, headers;
error: class / message / details / attempts; probe: region, attempts,
factory-call log, per-request path+headers+timeout log) and diffed
field-by-field (`/tmp/b7e2e/compare.py`).

## Scenario matrix (ids in the drivers)

- **Resolver (R01–R34, 34 rows)**: SA quad; quad-beats-OT; OT triple;
  partial-quad silent fallthrough (missing secret; empty-string members);
  invalid `MP_REGION` abort with a lower-rung winner present; empty-string
  env = absent (region, OT token); explicit axes; target three-axis apply;
  target+axis guard; bridge-only session incl. headers; settings-vs-bridge
  header collision; `[active]` fallback; both FR-024 no-account /
  no-project error texts; `MP_PROJECT_ID` non-digit, Nd-digit (`"٤٢"` —
  resolves on BOTH sides: pydantic-core `\d` and `/^\p{Nd}+$/u` agree);
  `MP_WORKSPACE_ID` `"0"`/`"abc"`/`"1_0"`/`" 42 "`/`"+42"`/Nd/`>2^53`;
  explicit workspace 0; explicit project `""`; env-beats-param on
  project+workspace; unknown account/target; bridge-project-none →
  account default; bridge-beats-active on account and workspace axes;
  target-project-beats-bridge.
- **Probe (P01–P14, 14 rows)**: success at each position; 401/403/500 and
  network failures at each position; all-401 (3-tuple attempts w/ bodies);
  all-network → `RegionProbeNetworkError`; mixed → generic
  `RegionProbeError`; empty order (`all([])` edge, `attempts: []`);
  custom order; single-region order; duplicate region (factory called
  twice); 4097-codepoint body with a non-BMP pair straddling the 4096 cut
  (truncation byte-identical); timeout plumb (2.5 observed at the client
  seam on both sides); `ConnectError`/`ConnectTimeout` reverse-table
  rendering on the all-fail path (`"ConnectError: DNS lookup failed"`,
  `"ConnectTimeout: timed out"` — byte-identical).
- **Credential probe (C01–C08)**: SA missing secret; OT no token/env;
  `token_env` unset AND set-but-empty; oauth_browser rejected; SA Basic
  header for non-ASCII username/secret (`Basic dXPDqXI6cMOkc3N3w7ZyZPCdkrM=`
  — UTF-8-then-base64 byte-identical, the btoa trap absent); inline vs
  env bearer; request URL `https://mixpanel.com/api/app/me` identical.
- **Namespaces (N01–N11)**: first-add active promotion; SA add without
  region; duplicate add; `use()` clears workspace; remove active+referenced
  (guard, force, orphan list, active cleared); `show()` with no active;
  `token()` SA→null / OT→inline; `session.use` target exclusivity;
  target-add unknown account; `targets.use` atomic three-axis apply incl.
  `default_project` rewrite; `accounts.test("")` → `"(none)"` (the
  arbiter's falsy-`or` fix — verified matching live Python).
- **login_unified (L01–L05)**: SA explicit name; SA derived name
  (`"Acme Corp"` → `acme-corp` both sides); OT env detection; `token_env`
  passed WITH explicit SA `account_type` (accepted on BOTH sides —
  no phantom guard invented in TS); multi-project no-picker E-8 (message
  byte-identical incl. the `((no domain))` rendering).
- **Naming (13 slugify rows + org-order)**: NFKD/ASCII-fold under
  ligatures, fullwidth, non-BMP `𝒳`→`x`, CJK→`""`, Ω-drop, dash edges,
  32-truncation — 13/13 byte-identical; `default_account_name` org pick +
  collision suffixing.
- **TS-only**: all 20 reachable `defaultAuthEffects()` members throw
  `UNPORTED_AUTH_SEAM` with `details.seam` = the member name; 14/14
  `region_probe.probe_region` vectors replayed from scratch inside a full
  `npm run conformance`: **3,251 → 3,244 PASS / 0 FAIL / 7 UNPORTED**
  (pre-flip shape, matches §2.8); secret-material scan over every
  error-kind payload in all four result files: zero hits on either side.

## Results

**77 paired scenarios; 6 rows diverged; after adjudication: 1 finding,
4 already-sanctioned/disclosed divergences, 1 fake-vs-real-ConfigManager
note. Zero UNDISCLOSED library divergences.**

### Finding B-E2E-F1 (MINOR, confirmed): duplicate `accounts.add` surfaces `ACCOUNT_EXISTS` in TS where Python raises plain `ConfigError`

- **Repro (N03)**: add account `"team"` twice through `mp.accounts.add`.
  - Python: `ConfigManager._apply_add_account` → **plain `ConfigError`**
    `"Account 'team' already exists."` (`config.py:446`). Python reserves
    `AccountExistsError` for the login_unified name-collision path only
    (`accounts.py:1689`).
  - TS: `accountsAdd` → `effects.config.addAccount` → the committed
    contract `auth-effects.ts:138` (*"@throws ConfigError - Duplicate name
    (`AccountExistsError`)"*) and the committed fake
    (`fake-auth-effects.ts:165` `throw new AccountExistsError(name)`) →
    **`AccountExistsError`, code `ACCOUNT_EXISTS`**, details
    `{account_name: "team"}`. Message text identical.
- **Why it matters**: R5 makes codes (not messages) the contract; a
  code-matching consumer sees `ACCOUNT_EXISTS` vs `CONFIG_ERROR` across
  the languages, and B8-N1 will implement the on-disk `ConfigManager` to
  the interface JSDoc, baking the divergence into the real path. The
  class family is preserved (`AccountExistsError extends ConfigError`),
  so `catch (ConfigError)` parity holds — hence MINOR, not MAJOR.
- **Ask**: arbiter either (a) aligns the `ConfigWrites.addAccount` JSDoc +
  fake to plain `ConfigError` (message already identical), or (b)
  sanctions the strengthening with a discrepancy-log entry the B8 packet
  inherits. Option (a) is a two-line change with no test-behavior impact
  beyond the fake's throw site.

### Adjudicated as already sanctioned / disclosed (no action)

1. **R10 / N08 — target-exclusivity guard class**: Python bare
   `ValueError`, TS `ParamValidationError` `WS1_TARGET_MUTUALLY_EXCLUSIVE`,
   message byte-identical. Packet §2.2 / Caution #14 mandates exactly this
   mapping. MATCH-BY-DESIGN.
2. **R33 — `MP_WORKSPACE_ID="9007199254740993"` (2^53+1)**: Python
   resolves workspace `9007199254740993`; TS raises coded `ConfigError`
   `"…not a positive integer."` `{env_var, value}`. Packet §2.2 sanctions
   the mapping (Discrepancy #6/#7 family) and it is disclosed at
   `B7-A2-notes.md:78-82`. CONFIRMED-DISCLOSED.
3. **Org-order pick (Caution #13)**: `/me` orgs `{"200": Beta Org,
   "100": Acme Corp}` → Python derives `beta-org` (insertion order), TS
   derives `acme-corp` (JS integer-key hoisting); non-integer-like org
   keys (`zz`/`aa`) MATCH (`zed`). Reproduced exactly as ruled by the
   shard arbiter (standing disclosed divergence per the #9/#10 mechanism,
   per the `4c8946a` commit record). CONFIRMED-DISCLOSED. Note for
   Phase 4: this IS reachable via `login_unified` derived naming whenever
   live `/me` emits orgs out of ascending-id order.
4. **Network-failure rendering beyond the vector-locked row**: the
   committed reverse table renders `ECONNREFUSED → ConnectError` and
   `UND_ERR_CONNECT_TIMEOUT → ConnectTimeout` byte-identically to httpx
   (both verified end-to-end); unmapped cause codes fall back to
   `inner.name` per the disclosed best-effort (Caution #8). No corpus or
   Layer-3 surface locks the unmapped rows. ACCEPTED-AS-DISCLOSED.

### Note B-E2E-N1 (test-infra, no code change requested)

`fakeConfig().addAccount` auto-promotes the FIRST account to active —
mirroring `accounts.add` (FR-045) rather than `ConfigManager.add_account`
(which does NOT promote; promotion lives in the namespace's `_mutate`
transaction, `accounts.py:472-489`). Correct for the namespace suites it
serves, but a resolver test seeding accounts through the fake and relying
on an EMPTY `[active]` must reset `state.active` (this harness did).
Flagging so B8's real `ConfigManager` port doesn't copy the promotion into
`add_account` itself — the interface JSDoc (`auth-effects.ts:125-127,
133-134`) binds the promotion to `addAccount`, which is faithful to the
NAMESPACE transaction but not to the underlying `ConfigManager.add_account`
seam name it cites. B8-N1 should implement the promotion exactly once (in
whichever layer it lands) and translate `test_config.py`'s
non-promoting `add_account` asserts against it.

### Field-equality highlights (things that could have diverged and did not)

- Resolved sessions matched on every field including revealed secret
  values, `default_project` propagation, header maps, and the exact
  FR-024 multi-line error texts (both shapes) and
  `Invalid project ID: '…'` / `Invalid workspace ID: …` texts.
- Probe attempt tuple shapes (2-tuple success mirror vs 3-tuple failure),
  factory short-circuit counts, duplicate-region double-invocation,
  `all([])` empty-order subclass, 4096-codepoint truncation with the
  surrogate pair intact, and per-request header/path/timeout logs matched
  exactly.
- `login_unified` end-state (summary fields, `[active]`, account
  `default_project`, me-cache write) matched on all three driven flows;
  flag-tolerance matched (no invented guard for `token_env`+SA).
- `accounts.test("")` post-arbiter behavior verified equal to live Python.

## Verdict

**GO** with 1 MINOR finding (B-E2E-F1) for the arbiter and 1 test-infra
note (B-E2E-N1) for the B8 packet author. No CRITICAL/MAJOR mismatch
found; every other observed divergence is already sanctioned or disclosed
with the correct scope. The 14 owned vectors replay green from scratch at
the post-arbiter state (3,244 / 0 / 7 pre-flip).
