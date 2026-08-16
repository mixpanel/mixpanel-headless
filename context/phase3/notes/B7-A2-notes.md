# B7-A2 — resolver core + region_probe + TokenResolver wiring (shard notes)

**Status**: DONE (module task, P3-2 a+b+b′+c). Packet:
`context/phase3/design/b7-packets.md` §2. Model: fable, ≤ high.
TS commit: see `mixpanel-headless-ts` main (B7-A2 shard commit).

## What landed (TS repo)

| file | role |
|---|---|
| `packages/core/src/auth/resolver.ts` | `resolveSession` + per-axis functions over INJECTED sources (`ResolverEnv` / `ResolverConfigSource` / `BridgeView` / `ResolverSources`, packet §2.2 — R9.4: no env reads, no I/O, no defaults); exports mirror `__all__` + `envWorkspaceId` |
| `packages/core/src/auth/region-probe.ts` | `probeRegion` / `probeClientFromFetch` / `probeBaseUrl` / `probeRegionForCredential` (packet §2.3, byte-for-byte checklist incl. close-in-finally, 2-vs-3-tuple attempts, `all([])` edge, cpSlice 4096 cap, code→httpx-class reverse table) |
| `packages/core/src/auth/account.ts` | `base64EncodeUtf8` now exported (R10.8: probe Basic header reuses the ONE UTF-8→base64 encoder) |
| `packages/core/src/auth/index.ts` | re-exports the two new modules |
| `conformance-runner/src/wire-auth.ts` (+ `bindings.ts` registration) | `region_probe.probe_region` binding — real `probeRegion` + real `probeClientFromFetch` over the harness fetch; `RecordingCallback` serves the `$type: callback` factory; NO batch-status flip (gate's duty) |
| Layer-3 (§2.4, all translated) | `test/auth/resolver.test.ts` (31 Python tests + `Test042::TestResolverEdgeCases` + packet §2.2 rule locks = 46), `resolver.pbt.test.ts` (5 properties, same strategy shapes), `region-probe.test.ts` (16 Python tests + 2 guard locks = 18), `account-edge.test.ts` (13), `session-replace.test.ts` (5), `session-replace.pbt.test.ts` (9) — every mechanism substitution header-cited to packet §2.2/§2.4 |
| `throwaway/b7-a2/{resolver-truth,probe-branches}.ts` + `RUN.md` | R10.9 harness (§2.6) |
| Re-anchors | `conformance-runner/test/runner.test.ts` (2 tests) + `differential/test/oracle-protocol.test.ts` (2 tests) → `oauth_flow.refresh_tokens` (see disclosure 4) |

## Checkpoint numbers (2026-08-16)

- `npm run conformance`: **3,251 — 3,244 PASS / 0 FAIL / 7 UNPORTED**
  (corpus @ `70c904dc598d`) = the §2.8 pre-flip expectation (3,230
  baseline + the 14 `region_probe.probe_region` vectors
  passing-while-pending; 7 remaining = `oauth_flow.refresh_tokens`, B8).
  All 14 vector ids of §2.3 replay green on the first run.
- `npm run check`: green (typecheck ×5 workspaces, eslint incl. the
  R9.1 purity boundary — no `node:*` / `process.env` in core — prettier,
  9,213 vitest tests, browser-bundle smoke).

## R10.9 RUN record (mirror of `throwaway/b7-a2/RUN.md`)

```
npx vite-node throwaway/b7-a2/resolver-truth.ts
npx vite-node throwaway/b7-a2/probe-branches.ts

resolver-truth: checks 788 (incl. 600 fuzz runs, seed 20260816)  failures 0  fuzz-divergences 0
probe-branches: checks 660 (incl. 600 fuzz runs, seed 20260817)  failures 0  fuzz-divergences 0
```

| group | checks |
|---|---:|
| account-axis bitmap 2^6 vs `firstPresent` mini-model | 64 |
| project-axis 2^4 × 3 account states (superset of the packet's 32) | 48 |
| workspace-axis 2^5 incl. all-absent → null terminal | 32 |
| resolver error rows + rule locks (invalid `MP_REGION` ± lower-rung winner; non-digit / Nd / No `MP_PROJECT_ID`; `MP_WORKSPACE_ID` "abc"/"0"/"-1"/"1.5"/>2^53 + grammar acceptances `1_0`/` +42 `/Nd; empty-string env ALL vars; partial SA quad ×4; SA-beats-OT; unknown account/target; target+axis guard ×3; header-merge collision; no-account; no-project both shapes; explicit workspace 0/−5; explicit project non-digit/empty) | 32 |
| resolver mandatory edge set (`""`/`"𝒳"` through account/target/project; `18.0`/`1.5` through workspace; `"𝒳"`/`"18.0"` through env vars) | 12 |
| resolver fast-check fuzz vs 30-line mini-model (seed **20260816**, 600 ≥ 500 budget) | 600 |
| probe branches: success at pos 1/2/3 + factory short-circuit counts + close()-exactly-once; 401/403/404/500 at each position (verbatim, no per-status branching); network error at each position + `[region, 0, "ConnectError: msg"]` rendering; all-401 / all-network (subclass-of) / mixed both arrangements; order `["eu","us"]` / `["eu"]` / `[]` (the `all([])` edge → `RegionProbeNetworkError`, `attempts: []`, factory never invoked) / `["us","us"]` (probed twice); body cap 4095/4096/4097 + `"𝒳"` surrogate straddle at the cut + empty + edge-set strings verbatim; headers verbatim (incl. empty map) + `/api/app/me` + timeout 5.0 default / 2.5 / 18.0 / 1.5 plumbed | 47 |
| `probe_region_for_credential`: SA missing username/secret/both; Basic = base64(UTF-8) non-ASCII lock (independent manual encoder); inline token wins over `token_env`; `token_env` present / empty / unset; neither source; `oauth_browser` rejected; narrate sequence verbatim; `probeBaseUrl` ×6 shapes (std/trailing-slash/query+fragment/port/bare-host/http-versioned); `probeClientFromFetch` end-to-end network rendering | 13 |
| probe fast-check fuzz vs probe mini-model (independent cpSlice; invocation + close counts asserted; seed **20260817**, 600 ≥ 500 budget) | 600 |
| **total** | **1448** |

Zero divergences in both fuzz families (zero-divergence table: empty).
Both harness files deterministic apart from the seeded fc runs.

## Decisions / disclosures (review-pair + arbiter input)

1. **Packet §2.2 Nd example corrected by live CPython probe**
   (2026-08-16, uv / CPython 3.14.6, this repo):
   `MP_PROJECT_ID="٤٢"` passes `str.isdigit()` AND
   `Project(id="٤٢")` (pydantic-core Rust-regex `\d` is Unicode) —
   **Python RESOLVES** with `project.id == "٤٢"`; the packet's claimed
   second-stage "Invalid project ID" failure for Nd does not exist.
   TS matches Python (guard `/^\p{Nd}+$/u`; `parseProject`
   `/^\p{Nd}+$/u`). The REAL two-stage split is `Numeric_Type=Digit`
   codepoints outside Nd (probe: `"²".isdigit() is True`,
   `Project(id="²")` raises): Python → ConfigError "Invalid project
   ID"; TS (no Numeric_Type regex property) fails the GUARD instead →
   ConfigError "must be a digit string" with `{env_var, value}`
   details. **Same class + code** (`ConfigError` / `CONFIG_ERROR`);
   message + details differ. `TODO(port)` at the guard
   (`resolver.ts::resolveProjectAxis`). **Escalated to the shard
   arbiter** (packet §2.2 says "match CPython" — byte-parity would need
   a pinned Numeric_Type=Digit generated table, a B0-1-style job;
   arbiter to rule: accept the disclosed class-level parity or
   commission the table).
2. **`MP_WORKSPACE_ID` > 2^53−1** → `pythonInt` `PY_INT_UNSAFE_INTEGER`
   mapped to the same "not a positive integer" ConfigError where
   CPython would parse and use the big int. Pre-sanctioned by packet
   §2.2 (Discrepancy #6/#7 family); not vector-observable; harness row
   `"9007199254740993"`.
3. **Reverse table for network-error rendering** (Caution #8): committed
   in `region-probe.ts` — `ECONNREFUSED → ConnectError`,
   `UND_ERR_CONNECT_TIMEOUT → ConnectTimeout`, `UND_ERR_SOCKET →
   ReadError`, fallback inner-cause `name`. Vector-locked for
   `ECONNREFUSED` only; a fired TS timeout clock renders
   `TimeoutError: ...` where httpx distinguishes
   `ConnectTimeout`/`ReadTimeout` — principled best-effort per the
   packet, disclosed here.
4. **Pending-exemplar re-anchors pulled FORWARD from gate spec §4.3**:
   binding the name breaks bound-name anchors at BIND time —
   `runner.test.ts` ("mapped-but-unbound" + setup-gating probes) and
   `oracle-protocol.test.ts` (two UNPORTED-scope probes) re-anchored to
   `oauth_flow.refresh_tokens` in the shard commit (the B6-BIND
   precedent: each anchor's own comment trail re-anchors at the bind
   wave). `batch-status.test.ts:86-87,240-243` anchors UNTOUCHED — they
   assert pending STATUS, valid until the gate flip; §4.3 keeps that
   duty at the gate.
5. **`sessionReplace` returns the same `headers` Map reference on
   preserve** (as Python `model_copy` shares the mapping object) — the
   `test_replace_returns_new_object` twin asserts new SESSION identity
   only, matching Python.
6. **Fuzz domains annotation-constrained** per Discrepancy #8 /
   user-ratification 1: names `[a-zA-Z0-9_-]`, projects digit strings,
   workspaces 1..2^31−1; out-of-annotation inputs excluded by
   construction.

## Deferral notes for A1 / B8 / the gate

- A1 consumes: `resolveSession(options, sources)`, `resolveProjectAxis`,
  `envWorkspaceId`, `probeRegionForCredential` (§2.5) — all exported
  from `auth/resolver.ts` / `auth/region-probe.ts` (also via
  `auth/index.ts`).
- B8 implements BY NAME: `ResolverEnv` (process.env),
  `ResolverConfigSource` (TOML ConfigManager), `BridgeView`
  (bridge.py), on-disk `TokenResolver`; plus the `getEnv` /
  `fetchImpl` wiring of `probeRegionForCredential`.
- Gate (§4): flip `region_probe.` → done (expected report 3,244/0/7 —
  ALREADY the observed pre-flip numbers since bound names replay while
  pending; the flip only ratchets stragglers); re-anchor
  `batch-status.test.ts` rows; delete `throwaway/b7-a2/` after arbiter
  sign-off.

## Progress checklist (final)

- [x] Layer-3 tests translated (§2.4) — 6 files, all green
- [x] `packages/core/src/auth/resolver.ts` (injected sources, §2.2)
- [x] `packages/core/src/auth/region-probe.ts` (§2.3)
- [x] `conformance-runner/src/wire-auth.ts` binding (inline, §2.7)
- [x] 14/14 `region_probe.probe_region` vectors PASS (pre-flip)
- [x] R10.9 harness `throwaway/b7-a2/` + RUN record (§2.6)
- [x] `npm run check` green; lint boundary green (R9.1)
- [x] Local commits (TS + this notes file)
