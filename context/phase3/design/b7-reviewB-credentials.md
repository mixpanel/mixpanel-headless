# B7 pair-B review — lens 1: CREDENTIAL SAFETY (BLIND pair)

**Status**: DONE · 2026-08-16 · fable, ≤ high. Scope: ALL B7 commits, BOTH
shards (A2 + A1), post-pair-A-arbiter state — TS `main` `64542e1` (B7-A2),
`e34d218` (B7-A1), `4c8946a` (arbiter fixes); Python support branch
`f492a4e..b8baee5` notes commits (the reviewA/arbiter commits were NOT
read — see Blindness below).

**VERDICT: GO — zero credential leaks found. 0 blocker / 0 major /
3 minor (all process/disclosure, no code defect).**

## Blindness attestation (packet §5 independence rule)

This reviewer did NOT read `b7-reviewA-semantics.md`,
`b7-reviewA-assertions.md`, `b7-reviewA-resolution.md`, or any review
section of other agents' outputs. Inputs: `phase3-playbook.md` v1.1,
`b7-packets.md`, the Python sources at HEAD, the TS diff
`db8e079..4c8946a`, the committed shard notes/RUN records (grepped for
token material — a lens duty), and fresh adversarial probes. Where TS
code comments cite `b7-reviewA-resolution.md` rulings (SEM-F1/F2/N3,
R1), only the in-code citation text was consumed, not the files.

## 1. Reveal-site audit (§3.3 allowlist diff)

Python `get_secret_value()` sites in the B7 ranges (measured by grep at
HEAD):

| Python site | Purpose |
|---|---|
| `region_probe.py:246` | SA Basic header build |
| `region_probe.py:250` | inline oauth_token Bearer |
| `accounts.py:844` | `login` → `_FreshBrowserBearer` (in-memory pre-persist probe) |
| `accounts.py:1665` | `_login_unified_new_browser` → `_FreshBrowserBearer` |

TS `reveal()` sites in `packages/core/src` after B7 (exhaustive grep):

| TS site | Twin of |
|---|---|
| `auth/account.ts:585` (`accountAuthHeader`, Phase-2) | SA Basic header |
| `auth/region-probe.ts:382` | `region_probe.py:246` |
| `auth/region-probe.ts:387` | `region_probe.py:250` |
| `accounts/accounts-ops.ts:726` | `accounts.py:844` |
| `accounts/login-unified.ts:593` | `accounts.py:1665` |

**Exact 1:1 correspondence — no extra reveal introduced, none dropped.**
`accounts.token()` exposes the plaintext bearer via the resolver return
(string, not Secret) on both sides — Python's documented public
behavior (`accounts.py:931-962`), no `reveal()` needed. Test-side
`reveal()` calls (fake config/token stores, `fake-auth-effects.ts:77-99`)
are the designated store writes (Python's ConfigManager persists SA
secret / inline token plaintext in `config.toml`; tokens.json likewise).

## 2. Auth header construction — byte-for-byte vs Python

- **Basic**: `probeRegionForCredential` and `accountAuthHeader` share
  ONE encoder (`base64EncodeUtf8`, exported in the A2 commit per R10.8 —
  TextEncoder UTF-8 bytes → `btoa`, never `btoa` on raw UTF-16; packet
  Caution #10). **Probe-verified byte-identical against live CPython**
  for a non-ASCII username+secret (`sa.üser` / `…é𝒳…`):
  `Basic c2Euw7xzZXI6U0VOVElORUwtaHVudGVyMi3DqfCdkrMtc2VjcmV0` from
  BOTH `probeRegionForCredential` (captured off the fake fetch) and
  `accountAuthHeader`, `=== base64.b64encode(f"{u}:{s}".encode())` in
  CPython 3.14. Bearer forms exact (`Bearer <raw>`; inline token wins
  over `token_env`; env indirection reads via injected `getEnv` at call
  time — the single documented env read, `region_probe.py:252`).
- **token_env unset/empty** → ConfigError naming the VARIABLE only:
  `--token-env 'MY_TOK' is unset; cannot probe region.` — matches
  Python's `{token_env!r}` rendering; the value never appears.
- **R2.9 per-request resolution**: `client.ts:755-766` re-resolves the
  OAuth bearer per call and caches ONLY the SA Basic header — exactly
  Python `api_client.py:406-412`. `fetchMe`/`accountsTest` build a
  fresh client per probe and pass the resolver, never a header.

## 3. Redaction / leak probes (fresh, adversarial)

Two reviewer-local probe scripts (run under vite-node, deleted after —
not committed) drove sentinel secrets (`SENTINEL-hunter2-é𝒳-secret`,
bearer + E2E variants) through:

- `Secret` primitive surfaces: `String()`, template literal,
  `JSON.stringify`, `util.inspect(depth:16, showHidden:true)`, spread,
  `Object.getOwnPropertyNames` — redacted everywhere (`#private` field
  + `toString`/`toJSON`/`Symbol.for('nodejs.util.inspect.custom')`).
- `probeRegionForCredential` SA + OT + token_env against all-401 /
  all-500 fakes → `RegionProbeError`/`RegionProbeNetworkError`:
  message, `details`, `toDict()`, `attempts`, full `inspect` incl.
  cause chains — clean; **the captured Authorization header string is
  not reachable from any error surface** (attempts carry
  `[region, status, body≤4096cp]` only, headers never echoed — parity
  with `region_probe.py:142-173`).
- `resolveSession` with the SA env quad (sentinel `MP_SECRET`) →
  resolved session `JSON.stringify` renders `"secret":"**********"`;
  the invalid-`MP_REGION` error path (details `{env_var, value}`)
  carries only non-secret env values (MP_REGION / MP_PROJECT_ID /
  MP_WORKSPACE_ID — same set as Python; MP_SECRET/MP_OAUTH_TOKEN are
  never echoed into any resolver error).
- A1 end-to-end: `accounts.test()` (SA sentinel, 401) →
  `AccountTestResult` clean (`error` = the Python default
  "Invalid credentials…" text; `error_details` carries only the B0
  detail bag — no headers by construction, `client/internals.ts`);
  `loginUnified` SA probe-failure → `RegionProbeError` clean;
  browser relogin E-3 with sentinel `OAuthTokens` → ConfigError clean;
  `JSON.stringify(OAuthTokens)` redacts both tokens.
- `parseAccount` failures (wrong-typed secret, smuggled extra key) —
  messages/details name FIELDS, never values.

**Zero hits across every probe.**

## 4. Committed artifacts (token-material grep)

- `throwaway/b7-a1/RUN.md`, `throwaway/b7-a2/RUN.md`,
  `context/phase3/notes/B7-A{1,2}-notes.md`: no bearer/Basic/token
  values, no credential-looking blobs.
- Full B7 diff scanned for JWT-ish (`eyJ…`) and ≥40-char base64 runs:
  only alphabet constants and paths. All test credentials are
  obviously-fake short strings.
- Harness sentinel sweep (`namespace-branches.ts:854-865` — §3.6 item
  4) is REAL (folded into all 72 captured error rows: message +
  `toDict()` JSON) and **reproduces exactly**: 352 checks / 0 failures /
  72 captured errors; `ops-fuzz` 600 sequences seed 20260818, 0
  divergences; A2 `resolver-truth` 788 checks seed 20260816 + 
  `probe-branches` 660 checks seed 20260817 — all match the RUN records.

## 5. Credential persistence in seams

- Atomic-publish ordering preserved: `accountsLogin` /
  `loginUnifiedNewBrowser` probe `/me` on the IN-MEMORY bearer
  (`freshBrowserBearer`) and call `tokenStore.writeTokens` only after
  the E-2 cross-check + name/orphan-dir guards pass; add()-failure
  rolls back via `removeAccountDir` (`accounts.py:826-877`,
  `:1616-1750` parity; `login-region-check.test.ts` locks
  "E-2 leaves no tokens").
- `meCache.put` persists `MeResponse` (no credential fields);
  `persistActiveToConfig` writes account NAME + project id + workspace
  only; `defaultAuthEffects()` members throw `UNPORTED_AUTH_SEAM`
  `{seam}` — details carry the seam NAME only.
- Config writes carry `Secret | string` credential fields to the
  designated config store — Python-parity (plaintext lives in
  `config.toml` on the Python side too).

## Findings (0 blocker / 0 major / 3 minor)

**CRED-F1 (minor, process)** — packet §3.3 requires "enumerate each
reveal call in the shard notes"; `B7-A1-notes.md` does not contain the
enumeration (it lives only in the `accounts-ops.ts` module header,
which additionally lists `token()` — a plaintext-return site, not a
`reveal()` site). §1 above IS the enumeration; fold it into
`B7-notes.md` at the gate.

**CRED-F2 (minor, disclosure, safe direction)** — TS `Secret` renders
`'**********'` for an EMPTY wrapped value where Pydantic `SecretStr`
renders `''` (CPython-verified). Phase-2-owned code (`secret.ts`,
unchanged in B7) newly load-bearing on the B7 surface; the only B7
`new Secret("")` site (`login-unified.ts:763`) is a defensive
unreachable fallback. MORE redaction, never less — no code change
wanted; record as a disclosed cosmetic divergence in the gate notes.

**CRED-F3 (minor, outbound B8 caution)** — `Secret.toJSON()` redaction
means any B8 writer that serializes an account/tokens via
`JSON.stringify` would PERSIST literal asterisks (silent credential
corruption, discovered only at next auth). The A1 fakes demonstrate the
correct pattern (`reveal()` at the designated write,
`fake-auth-effects.ts:77-99`); the B8 packet should state this rule
explicitly for `config.*`/`tokenStore.writeTokens`/`bridge.export`.

## Coverage attestation (orchestrator per-shard ruling)

- **A2 under lens 1**: resolver env-secret handling, probe header
  construction, attempts/error redaction, binding (`wire-auth.ts` —
  honesty-adjacent check: headers passed verbatim to the REAL
  `probeRegion`, no header assembly in the rig) — §§1-3.
- **A1 under lens 1**: namespaces, login/login_unified flows, effects
  bag, tokenStore ordering, workspace constructor sources, Layer-3
  `secret-redaction.test.ts` (faithful translation of
  `test_042_edge_cases.py:615-681` with header-cited mechanism
  substitutions; `JSON.stringify` is the stronger repr-substitute and
  is asserted) — §§1,3-5.
