# B7 design-lite packets — accounts/session/targets namespaces + resolver core + region probe

**Status**: v1.0 · 2026-08-16 · P3-6 step 1 output for batch B7 (fable, ≤ high).
Spec of record: `phase3-playbook.md` v1.1 (B7 rows: P3-1 `:223-234`, P3-3 doubling
`:380-387`, P3-5 flip `:663`, P3-6 sharding `:765-767`) + Discrepancies #7–#12 +
D-B4ARB-1 + `user-ratifications.md`. Inbound deferrals: `b6-packets.md` §13
(`:1021-1033`) — the `ResolverSeams` defaults, the `test_workspace_use.py` /
`test_workspace_init.py` / `test_workspace.py::TestCredentialResolution` /
`test_042_edge_cases.py` ledger splits. Ground state verified 2026-08-16:
Python `ts-port/phase2-contract-support` @ `5269674`-lineage (corpus pin
`70c904dc`); TS `main` @ `db8e079` (B6 gate closed: 3,230 PASS / 0 FAIL /
21 UNPORTED; only pending prefixes `region_probe.` ×14 + `oauth_flow.` ×7).

**Standing rules restated**: NO mutation testing `[SA1]`. R10.13 incremental
protocol on every agent. Python is the behavior arbiter. `analytics` READ-ONLY.
LOCAL COMMITS ONLY, both repos. B7 is fable-tier → bindings land INLINE in the
module task (P3-2 b′), and the R10.9 harness runs in the same task. **DOUBLED
review** (P3-3): two independent pairs + arbiter per shard — protocol in §5.

## §0 Shard map, labels, and execution order

| Shard | Contents | Vectors | Runs |
|---|---|---|---|
| **B7-A2** | resolver core (`resolve_session` precedence over injected sources) + `region_probe.py` (whole file) + TokenResolver protocol wiring + auth-model edge tests + the resolver-precedence fast-check PBT | **14** (`region_probe.probe_region`) | **FIRST** |
| **B7-A1** | `accounts` / `session` / `targets` namespace surfaces + `login_unified` + `naming.py` + the B6-deferred resolver test classes + the `ResolverSeams` real implementations | 0 | second (depends on A2) |

Σ vectors = **14** — the complete `region_probe.` budget (P3-1 `:103`). All 14
ids enumerated in §2.3; zero vectors carry any other B7 api (`accounts.*` /
`session.*` / `targets.*` / `naming.*` have no corpus presence — Layer-3 is
their only lock, the Risk-7 posture).

**Label note (recorded discrepancy, no scope change)**: the playbook P3-6 row
(`:765-767`) spells the shards "A1 resolver + region_probe + naming; A2
accounts + session + targets (depends on A1)". This packet keeps the
orchestrator's instantiated labels — **A2 = resolver/probe, A1 = namespaces** —
with the SAME dependency direction (resolver shard first). Content is
identical; only the labels are swapped. One placement deviation: `naming.py`
moves from the resolver shard to the namespaces shard (A1) because its only
consumer is `login_unified`'s name derivation (`accounts.py:493-589`) and its
Layer-3 (`test_naming.py`, `test_naming_pbt.py`) shares A1's fixtures; both
shards are the same tier and the doubled review covers both, so the binning is
review-neutral.

**R9 posture for the whole batch (CRITICAL)**: `packages/core` reads NO env
vars and imports NOTHING from `node:*` (R9.1/R9.4 — the lint boundary +
browser-bundle smoke must stay green). Every Python `os.environ` /
`ConfigManager()` / file / browser touch in these modules becomes an INJECTED
interface defined in B7 and implemented in B8 (`packages/node`). §3.2 is the
normative seam enumeration (B7-owned vs B8-owned, with the named
still-stubbed list).

---

## §1 Vector budget and gate arithmetic

Corpus pin `70c904dc` (`conformance-runner/corpus.config.json`), bundle
`conformance-runner/corpus/auth/test_region_probe.jsonl` (`$bundle.count: 14`,
`source_file: tests/unit/test_region_probe.py`). Baseline at B6 gate:
**3,230 PASS / 0 FAIL / 21 UNPORTED**. B7 gate flips `region_probe.` → `done`;
expected checkpoint: **3,244 PASS / 0 FAIL / 7 UNPORTED** (delta exactly +14;
the 7 remaining are `oauth_flow.refresh_tokens`, B8). No cross-batch setup
carry-over: none of the 14 vectors carries `call.setup[]` or `call.session`
(verified by jq scan 2026-08-16 — `input.client_factory` is a `$type: callback`
and the only state is per-vector).

---
## §2 Packet B7-A2 — resolver core + region probe + TokenResolver wiring (fable; runs FIRST)

### §2.1 Modules, Python line ranges at HEAD, TS homes

| Python source (range @ HEAD) | What | TS home |
|---|---|---|
| `_internal/auth/resolver.py:1-474` (whole file) | `_env_region` :56-78 · `_env_account_from_service_quad` :81-107 · `_env_account_from_oauth_token` :110-132 · `resolve_account_axis` :135-176 · `resolve_project_axis` :179-221 · `env_workspace_id` :224-253 · `resolve_workspace_axis` :256-289 · `_resolve_headers` :292-315 · `format_no_account_error` :318-330 · `format_no_project_error` :333-359 · `resolve_session` :362-465 · `__all__` :468-474 | `packages/core/src/auth/resolver.ts` (new) |
| `_internal/auth/region_probe.py:1-287` (whole file) | `ClientFactory` :44 · `_ME_PATH` :48 · `_MAX_RESPONSE_BODY_CHARS` :55 · `RegionProbeResult` :58-82 · `probe_region` :85-191 · `probe_region_for_credential` :194-287 (incl. `_factory` URL stripping :267-278) | `packages/core/src/auth/region-probe.ts` (new) |
| `_internal/auth/account.py:61-…` `TokenResolver` protocol (already ported: `packages/core/src/auth/account.ts:74`) | B7 work is WIRING only: the resolver core and A1 surfaces thread the existing `TokenResolver` through `sessionAuthHeader` (`auth/session.ts:378`) per R2.9 — auth header resolved PER REQUEST, never captured at construction. `OnDiskTokenResolver` (`token_resolver.py:57-288`) stays **B8-N2**; B7 tests inject in-memory fakes (the `_FreshBrowserBearer` twin, `accounts.py:91-128`) | no new file — imports |
| Auth-model edge residue (B6 ledger `:1032`): `tests/unit/test_042_edge_cases.py` classes `TestAccountNameBoundaries` :52-104, `TestOAuthTokenValidatorUnderCopy` :105-167, `TestSessionReplaceSentinel` :168-239, `TestResolverEdgeCases` :325-393 | Layer-3 only (models already ported at Phase 2) | tests, §2.4 |

`resolver.ts` exports mirror `__all__` (:468-474) plus `env_workspace_id`
(consumed by name from the W1-D1 seam — `lifecycle.ts:92`) and the injected-
source types below. `Region` runtime set: reuse the Phase-2 literal table
(`auth/account.ts`), never a re-derived list (the `_VALID_REGIONS` twin,
`resolver.py:53`).

### §2.2 Injected-source design (R9.4 — THE core decision of the shard)

Python reads `os.environ` inline and defaults `config=ConfigManager()` /
`bridge=load_bridge()` (`resolver.py:407-408`). The TS core takes **required
injected sources — no defaults, no I/O**:

```typescript
/** The six MP_* reads, as a plain readonly bag. B8 wires process.env. */
export interface ResolverEnv {
  readonly MP_USERNAME?: string;   readonly MP_SECRET?: string;
  readonly MP_PROJECT_ID?: string; readonly MP_REGION?: string;
  readonly MP_OAUTH_TOKEN?: string; readonly MP_WORKSPACE_ID?: string;
}
/** Config reads the resolver consults. B8's ConfigManager satisfies it. */
export interface ResolverConfigSource {
  getAccount(name: string): Account;            // throws coded ConfigError on unknown
  getActive(): ActiveSession;
  getTarget(name: string): Target;              // throws coded ConfigError on unknown
  getCustomHeader(): readonly [string, string] | null;
}
/** The bridge fields the resolver reads (bridge.py stays B8; this is the VIEW). */
export interface BridgeView {
  readonly account: Account;
  readonly project: string | null;
  readonly workspace: number | null;
  readonly headers: Readonly<Record<string, string>>;
}
export interface ResolverSources {
  readonly env: ResolverEnv;
  readonly config: ResolverConfigSource;
  readonly bridge: BridgeView | null;
}
export function resolveSession(
  options: { account?: string | null; project?: string | null;
             workspace?: number | null; target?: string | null },
  sources: ResolverSources,
): Session;
```

Rules the implementation must keep byte-for-byte:

- **Empty-string env = absent** for region/username/secret/project/token/
  workspace (`if not val` — `resolver.py:71,97,123,205,239`; watchlist #6:
  explicit `=== undefined || === ""` checks, never `!v` on numbers).
- **Invalid `MP_REGION` raises unconditionally** whenever the env-account
  synthesis runs — i.e. an invalid region ABORTS resolution even when an
  explicit `account=` param would win a lower rung (`resolver.py:73-78` via
  :96/:122 → :161-166). Details `{env_var: "MP_REGION", value}`.
- **SA quad beats OAuth-token env** (both complete → SA; `resolver.py:161-166`,
  PR #125). Partial quad falls through SILENTLY (:97-98) — no error.
- `MP_PROJECT_ID` non-digit → ConfigError with `{env_var, value}` (:207-211);
  digit check is `str.isdigit()` on the whole string — port as `/^\d+$/` over
  the raw string (NOT `pythonInt` — leading `+`, underscores, Nd digits must
  REJECT here exactly as `isdigit` accepts only decimal digit characters;
  note: `isdigit` accepts Unicode Nd — if fuzz finds an Nd case, match
  CPython: the check is `env_val.isdigit()`, so `"٤٢"` PASSES the guard and
  then fails `Project(id=...)`'s `^\d+$` pattern → ConfigError "Invalid
  project ID" — two DIFFERENT error paths; keep both).
- `env_workspace_id`: `int(env_val)` → `pythonInt` twin (R11.7 — underscores,
  whitespace, signs behave like CPython `int()`); `<= 0` → same ConfigError
  message shape (:238-253). `PY_INT_UNSAFE_INTEGER` beyond 2^53−1: map to the
  same ConfigError (coded, not a crash) — record in RUN notes (Discrepancy
  #6/#7 family; not vector-observable).
- **Target mutual exclusion** (:400-405): port to the SAME coded error the W1
  guard used — `ParamValidationError` `WS1_TARGET_MUTUALLY_EXCLUSIVE`
  (`lifecycle.ts:191`; Python raises bare `ValueError` — R5 codes-not-messages
  maps it to the existing code; do NOT mint a second code for the same guard).
- Header merge: settings entry first, bridge overrides on collision
  (`_resolve_headers` :309-315).
- Axis chains verbatim: account env→explicit→target→bridge→`[active].account`
  (:161-176); project env→explicit→target→bridge→`account.default_project`
  (NO `[active].project` rung — FR-033, :205-221); workspace
  env→explicit→target→bridge→`[active].workspace`, `None` terminal legal
  (:279-289). FR-024 error text ported as-is (`:318-359`) — messages out of
  contract (R5.4) but ported anyway; Layer-3 asserts key substrings as Python
  does.
- `workspace` explicit `0`/negative reaches `WorkspaceRef` validation →
  ConfigError `"Invalid workspace ID: …"` (:450-456); project pattern failure
  → ConfigError `"Invalid project ID: …"` (:436-441).
- Purity: no source mutation, deterministic on identical inputs
  (`test_resolver.py::TestNoSideEffects` :223 re-expresses as frozen-input /
  no-mutation asserts — the TS twin cannot mutate `process.env` by
  construction, but the sources object must come back untouched).

### §2.3 Region probe port spec + the 14 vectors

TS shape (binding maps `call.input` keys by the standard naming rules):

```typescript
export interface ProbeResponse { readonly status: number; readonly text: string; }
export interface ProbeClient {
  get(path: string, opts: { headers: Readonly<Record<string, string>>;
      timeoutSeconds: number }): Promise<ProbeResponse>;
  close(): void;
}
export type ClientFactory = (region: Region) => ProbeClient;
export interface RegionProbeResult {
  readonly region: Region;
  readonly attempts: ReadonlyArray<readonly [Region, number]>;  // 2-tuples
}
export function probeRegion(clientFactory: ClientFactory,
  headers: Readonly<Record<string, string>>,
  options?: { timeoutSeconds?: number; order?: readonly Region[] },
): Promise<RegionProbeResult>;
/** The real client construction (B8's probeRegionForCredential + the binding use it). */
export function probeClientFromFetch(fetchImpl: typeof fetch, baseUrl: string): ProbeClient;
/** Pure URL-stripping twin of the _factory base derivation (:276-277). */
export function probeBaseUrl(appUrl: string): string;
export function probeRegionForCredential(options: {
  account_type: AccountType; username: string | null; secret: Secret | null;
  token: Secret | null; token_env: string | null;
  narrate?: ((msg: string) => void) | null;
  getEnv: (name: string) => string | undefined;   // R9.4 seam — B8 wires process.env
  fetchImpl: typeof fetch;
}): Promise<Region>;
```

Byte-for-byte checklist (each line = a review-pair assertion):

1. Walk `order` (default `["us","eu","in"]`), one client per region via the
   factory, `GET /api/app/me` with the caller headers + per-region timeout
   budget; **first 200 short-circuits** (:145-166) — later regions' factories
   NEVER invoked (vector `test_us_succeeds_first_short_circuits` locks
   `callback_calls.client_factory == [["us"]]`).
2. **`close()` in a `finally` per region** (:174-175) — including the 200
   path (close BEFORE returning) and the network-error `continue` path.
3. Success attempts list = failure tail (as 2-tuples, bodies DROPPED) +
   `[region, 200]` (:163-166). Error attempts are **3-tuples**
   `[region, status, body]` (:156, :167-173) — two distinct tuple shapes;
   `RegionProbeError.attempts` / `details.attempts` carry the 3-tuple form
   (TS `RegionProbeAttempt`, `errors.ts:1022` — already shaped).
4. Non-200 body capture: `response.text[:4096]` → `cpSlice(text, 0, 4096)`
   (R11.6 — codepoints, never UTF-16 units; `_MAX_RESPONSE_BODY_CHARS` :55).
5. Network failure → attempt `[region, 0, "<HttpxClass>: <message>"]`
   (:152-157, rendering `f"{type(exc).__name__}: {exc}"`). **TS rendering
   spec**: `probeClientFromFetch` routes through the B0 transport adapter
   (`client/transport.ts:297-322`, R2.10 normalization to
   `MixpanelHttpError`); the probe then renders
   `<httpx-equivalent class>: <cause message>` via a small committed
   `cause.code → httpx class` reverse table in `region-probe.ts`
   (`ECONNREFUSED → "ConnectError"`, `UND_ERR_CONNECT_TIMEOUT →
   "ConnectTimeout"`, `UND_ERR_SOCKET → "ReadError"`, fallback
   `cause.name`). Rationale: the vector
   `test_all_network_errors_raise_network_subclass` asserts
   `details_contain.attempts` `["us", 0, "ConnectError: DNS lookup failed"]`
   — the harness cause carries the RECORDED message
   (`transport-errors.ts:164-171`) but `causeName` is `"Error"` for
   ConnectError, so the class name must come from the code. This is the D12
   table's dual and lives in the LIBRARY (documented; the one corpus-
   observable row is `ECONNREFUSED`); Layer-3 keeps Python's own loosened
   assert (`test_region_probe.py:167`: message OR class-name substring).
6. All-failed classification (:182-191): `every(status === 0)` over the
   failure list → `RegionProbeNetworkError` (`OAUTH_NETWORK_UNREACHABLE`),
   else `RegionProbeError` (`OAUTH_REGION_PROBE_FAILED`) — both already in
   `errors.ts:1041+` / `errors-codes.gen.ts:70-71` with subclass relation.
   **`order` empty → `every` over `[]` is `true` → `RegionProbeNetworkError`
   with `attempts: []`** (Python `all([])` — port this edge verbatim; harness
   item, §2.6).
7. `probe_region_for_credential` (:194-287): SA → `Basic
   base64(utf8(username + ":" + secret))` — **UTF-8 bytes then base64, never
   `btoa` on raw UTF-16** (:246-247); oauth_token → inline `token` wins, else
   `getEnv(token_env)` where unset/EMPTY string → ConfigError
   (:252-260 — `if not bearer`); other account types → ConfigError
   (:262-265). Base URL per region: `probeBaseUrl(ENDPOINTS[region].app)` —
   scheme+host only, path/query/fragment dropped (:276-277; use the URL
   parser's `origin`, equivalent to `urlunsplit((scheme, netloc, "", "", ""))`
   for http(s); R2.13's concat-only rule governs REQUEST path assembly, not
   this read-only parse — cite this line in the code comment). `narrate`
   messages ported verbatim (:280-287) but out of contract (R5.4).
8. Timeout: `timeoutSeconds` default 5.0, threaded to `ProbeClient.get` per
   request (Layer-3-only observable; R2.12 — the seconds→ms conversion lives
   inside `probeClientFromFetch` at the transport call, serialized values
   keep seconds).

**The 14 vector ids** (bundle `auth/test_region_probe.jsonl`, prefix
`auth/region_probe.probe_region/test_region_probe-`):

```
testproberegionerrorpaths-test_all_network_errors_raise_network_subclass
testproberegionerrorpaths-test_all_regions_401_raises_with_full_attempts
testproberegionerrorpaths-test_mixed_network_and_auth_failure_raises_generic
testproberegionerrorpaths-test_network_error_rendered_as_status_zero
testproberegionhappypaths-test_eu_succeeds_after_us_fails
testproberegionhappypaths-test_in_succeeds_after_us_and_eu_fail
testproberegionhappypaths-test_us_succeeds_first_short_circuits
testproberegionordering-test_custom_order_eu_first
testproberegionordering-test_custom_order_skips_unlisted_regions
testproberegionresponsebodycap-test_oversized_response_body_truncated_to_4kib
testproberegionresponsebodycap-test_small_response_body_preserved_verbatim
testproberegionsendsheaders-test_authorization_header_forwarded
testproberegionsendsheaders-test_request_targets_me_endpoint
testproberegiontimeout-test_timeout_is_passed_to_request
```

Coverage note: `TestRegionProbeFactoryURLStripping` (:379-486) recorded no
vectors (`probe_region_for_credential` is registry-audited-out,
`registry.py:562-563`) — Layer-3 only, against `probeBaseUrl`.

### §2.4 Layer-3 translation scope (A2)

| Python source | Classes / properties | TS test file |
|---|---|---|
| `tests/unit/test_resolver.py` (443 lines, 31 tests) | `TestAccountAxisPriority` :62, `TestProjectAxisPriority` :126, `TestWorkspaceAxisPriority` :163, `TestTargetMutualExclusion` :190, `TestNoSideEffects` :223 (re-expressed as no-source-mutation), `TestErrorMessages` :255, `TestCrossSourceOrdering` :268 | `packages/core/test/auth/resolver.test.ts` |
| `tests/pbt/test_resolver_pbt.py` (173 lines, 5 properties) | determinism :81, project-axis independence :98, workspace-axis independence :117, env-wins-project :137, env-wins-workspace :160 — same strategy shapes (name alphabet `[a-zA-Z0-9_-]{1,12}`, project `^[1-9][0-9]{0,9}$`, workspace 1..2^31−1); the tmp-dir `ConfigManager` fixture (`_build_cm` :46-73) becomes an in-memory `ResolverConfigSource` fake; `monkeypatch.setenv` becomes an env-bag literal | `packages/core/test/auth/resolver.pbt.test.ts` |
| `tests/unit/test_region_probe.py` (486 lines, 16 tests, 8 classes) | all of §2.3's classes + `TestRegionProbeFactoryURLStripping` :379 (against `probeBaseUrl` + a factory-construction spy — the `monkeypatch.setattr(rp_mod, "probe_region", …)` spy translates to an injected probe fn or direct `probeBaseUrl` asserts, header-cite the substitution) | `packages/core/test/auth/region-probe.test.ts` |
| `tests/unit/test_042_edge_cases.py` (B6 ledger `:1032`) | `TestResolverEdgeCases` :325-393 → resolver.test.ts (same file, cited section); `TestAccountNameBoundaries` :52-104 + `TestOAuthTokenValidatorUnderCopy` :105-167 (pin: copy does NOT re-validate — TS twin pins spread/`sessionReplace` behavior over the frozen parse-once model, header-cite the mechanism substitution) + `TestSessionReplaceSentinel` :168-239 (workspace `null` clears vs OMITTED preserves — `sessionReplace` sentinel semantics, `auth/session.ts:393-424`) | `packages/core/test/auth/account-edge.test.ts`, `packages/core/test/auth/session-replace.test.ts` |
| `tests/pbt/test_session_pbt.py` (202 lines) | the `replace` properties :97-155 + `auth_header` format property :168+ (TypeAdapter-roundtrip property :157 — verify against the existing Phase-2 `session.test.ts` parse coverage; translate unless literally duplicate, header-cite either way) | `packages/core/test/auth/session-replace.pbt.test.ts` |

R10.2 discipline: no assertion dropped/loosened without a file-header design
citation. The known substitutions (monkeypatch-spy → injected fn; env
monkeypatch → source bag; `model_copy` → spread) each get a header cite to
THIS packet section.

### §2.5 R10.10 consumers (signatures pasted, per P3-1 format)

- **`Workspace.use()` / constructor** consume the resolver THROUGH the W1-D1
  seams — the consumer contract is the `ResolverSeams` interface
  (`packages/core/src/workspace-members/lifecycle.ts:61-102`), pasted:

  ```typescript
  export interface ResolverSeams {
    resolveSession(args: { readonly target: string }): Promise<Session>;
    getAccount(name: string): Promise<Account>;
    resolveProjectAxis(args: { readonly explicit: string | null;
      readonly target_project: string | null; readonly account: Account;
    }): Promise<string | null>;
    envWorkspaceId(): number | null | Promise<number | null>;
    persistActive(session: Session): void | Promise<void>;
  }
  ```

  A1 implements 4 of the 5 over this shard's exports (§3.2). NOTE the seam's
  `resolveSession` is target-only (the `use(target=…)` path); the FULL
  `resolveSession(options, sources)` is additionally consumed by the B7
  constructor-resolution work in A1 and by B8's node-level default wiring.
- **`accounts.login_unified` / `_login_unified_new_credential`**
  (`accounts.py:1030-1274`, :1753-1912) consume `probeRegionForCredential`
  (A1, via the injected env/fetch seams).
- **B8 (`packages/node`)** implements `ResolverEnv` (process.env),
  `ResolverConfigSource` (TOML ConfigManager), `BridgeView` (bridge.py port)
  and the on-disk `TokenResolver`; B8's packet consumes every §2.2 interface
  BY NAME.
- **CLI**: out of scope (plan D4) — `probe_region_for_credential`'s `narrate`
  param is kept for parity but has no in-repo TS consumer yet.

### §2.6 R10.9 harness spec — `throwaway/b7-a2/`

No oracle surface exists for auth (playbook Risk 7: no cross-language fuzz
bridges; compensating controls = full Layer-3 + doubled review) — the harness
is the edge set + VectorFetch-driven branch enumeration + an EXHAUSTIVE local
truth table, with fast-check fuzz against an independent mini-model (≥500
examples per surface, P2-9 budget kept even without the bridge).

**probe_region — EVERY branch** (each row through `probeClientFromFetch` over
`createVectorFetch`-style canned interactions or hand fakes):

1. Success at position 1 / 2 / 3 of the default order (per-region success);
   factory-invocation short-circuit counts asserted each time.
2. Per-region non-200: 401, **403**, 404, 500 at each position with success
   after (status lands verbatim in attempts — there is no per-status
   branching inside the probe, lock that by asserting 403/500 flow the same
   as 401).
3. Per-region network error at each position (rejected fetch) with success
   after; attempt rendered `[region, 0, "<class>: <msg>"]`.
4. All-401 → `RegionProbeError` `OAUTH_REGION_PROBE_FAILED`, 3 attempts in
   order with bodies.
5. All-network → `RegionProbeNetworkError` `OAUTH_NETWORK_UNREACHABLE`
   (subclass-of check).
6. Mixed net+HTTP in BOTH arrangements → generic `RegionProbeError`.
7. Order semantics: custom order `["eu","us"]`; single `["eu"]` (no
   fall-through); **empty `[]` → `RegionProbeNetworkError` with
   `attempts: []`** (the `all([])` edge); duplicate region `["us","us"]`
   (probed twice — factory called twice).
8. Body cap boundary: lengths 4095/4096/4097; a non-BMP codepoint (`"𝒳"`)
   straddling the 4096 cut (cpSlice must not split the surrogate pair);
   empty body; body that is the mandatory edge-set strings.
9. Header forwarding verbatim (incl. empty headers map); `/api/app/me` path;
   timeout plumb (2.5 observed at the fake client).
10. `probe_region_for_credential` branches: SA missing username/secret →
    ConfigError; token inline; token_env set+present / set+empty / set+unset
    → ConfigError; non-probeable account type → ConfigError; base64 header
    for a non-ASCII username/secret (UTF-8 encoding lock); `probeBaseUrl`
    over the Layer-3 URL shapes + query/fragment/port variants.

**resolver — precedence truth table, EXHAUSTIVE**: enumerate presence
bitmaps per axis — account 2^6 (env-SA-quad, env-OT-triple, explicit, target,
bridge, `[active].account`) = 64; project 2^5 (env, explicit, target,
bridge-with-project, account-default) = 32, run under both
account-with-default and account-without-default; workspace 2^5 (env,
explicit, target, bridge-with-workspace, `[active].workspace`) = 32 plus the
all-absent → `null` terminal. Assert the winner is the highest-priority
present source, every combination, against a 10-line independent mini-model.
Plus the error rows: invalid `MP_REGION` (with and without a lower-rung
winner present — must STILL raise), `MP_PROJECT_ID` non-digit, Nd-digit
`MP_PROJECT_ID` (two-stage failure, §2.2), `MP_WORKSPACE_ID` non-int / `"0"`
/ negative / `>2^53`, empty-string env for every var (falls through, never
errors), partial SA quad ×4 (each member missing), both env sets complete
(SA wins), unknown account/target names, target+axis kwarg guard, header
merge collision (bridge wins), no-account error, no-project error (with and
without a resolved account — two message shapes :333-359).

**fast-check fuzz**: ≥500 examples over randomized source bags + option bags
(valid domain per Discrepancy #8 — annotation-constrained) diffed against the
mini-model; ≥500 over probe interaction sequences (random status/network
mixes and orders) diffed against a probe mini-model. Seeds + counts + zero-
divergence table → RUN record in `context/phase3/notes/B7-A2-notes.md`.
Mandatory edge set (`18.0`, `1.5`, `true`, `null`, `[]`, `""`, `"𝒳"`) pushed
through every string/number-typed param the annotations admit.

### §2.7 Binding plan (inline, fable — P3-2 b′ for a fable-tier batch)

- **Registry name**: `region_probe.probe_region` — Python recorder entry
  `conformance/record/registry.py:575-580` (`KIND_WIRE_API`, capability
  `auth`, target `region_probe:probe_region`). NO other B7 api name exists in
  the corpus or the api-index.
- **TS home**: new `conformance-runner/src/wire-auth.ts`, registered from
  `bindings.ts` alongside the other wire modules. Rig code = fable (P3-3) —
  satisfied, the module task is fable.
- **Callback rebuild**: `call.input.client_factory` is `$type: "callback"` —
  the codec substitutes a `CallbackStub` (`codecs.ts:150-154`, case
  `"callback"` :480) whose recorded arg log diffs against
  `expect.callback_calls.client_factory` (`runner.ts:278-300`). The binding
  composes: `factory = (region) => { stub.fn(region); return
  probeClientFromFetch(context.harness.fetch, "https://test.invalid"); }` —
  the recorded scheme_host is `https://test.invalid` on all 14 vectors
  (mirrors the Python fixture `_client` base_url, `test_region_probe.py:44-47`).
- **Binding honesty (P3-5 rule 3)**: the binding calls the REAL exported
  `probeRegion` with the REAL `probeClientFromFetch` — it never issues fetches
  itself, never classifies errors itself, never assembles attempts. The
  arbiter checks this explicitly.
- **Input mapping**: `headers` verbatim; `timeout_seconds → timeoutSeconds`,
  `order` (array of region strings) — standard `naming.ts` snake→camel
  handling; absent kwargs → omit (defaults inside the library).
- **Result encoding**: return the `RegionProbeResult` as
  `{region, attempts}` with attempts as arrays (the canonicalizer's tuple
  handling matches the recorded `expect.result`). Error path: throw the real
  `RegionProbeError`/`RegionProbeNetworkError` — the runner encodes
  `{class, code, details_contain}`; `details.attempts` must carry the
  3-tuples (already the `errors.ts:1042-…` shape).
- **Determinism seams**: none needed (no sleep/random/now in the probe path;
  timeout is not vector-observable).
- **NO batch-status flip in the module commit** — the flip is the gate's
  (§4). Vectors replay green while `region_probe.` is still `pending`
  (bound-name-while-pending is the designed B4 pattern, playbook P3-5 §4).

### §2.8 Done-criteria (A2)

Files on disk (`auth/resolver.ts`, `auth/region-probe.ts`, `wire-auth.ts`,
tests §2.4) + `tsc --strict` clean + translated Layer-3 green + all 14
vectors PASS via `npm run conformance` (report: 3,244 PASS equivalent
pre-flip: 3,230 PASS + 14 passing-while-pending; 0 FAIL) + harness RUN record
written + JSDoc complete + lint boundary green (no `node:*`, no
`process.env` in core) + one local TS commit. Python repo: notes file
committed (`context/phase3/notes/B7-A2-notes.md`); `just check` only if
Python files were touched (none planned).

---
## §3 Packet B7-A1 — accounts/session/targets namespaces + naming + ResolverSeams implementations (fable; after A2)

### §3.1 Modules, Python line ranges at HEAD, TS homes

| Python source (range @ HEAD) | What | TS home |
|---|---|---|
| `accounts.py:1-2028` (whole file) | module helpers :64-351 (`ProjectPicker` :64-70 · `ProgressFactory` :71 · `_FreshBrowserBearer` :91-128 · `_narrate` :132-149 · `_fetch_me` :150-200 · `_assert_project_region_matches` :201-241 · `_build_test_failure_result` :242-277 · `_safe_rmtree_warn` :278-303 · `_DOMAIN_TO_REGION`/`_domain_to_region` :304-351) · `list` :352-360 · `add` :361-492 · `_derive_account_name_for_credential` :493-589 · `update` :590-632 · `remove` :633-650 · `use` :651-676 · `show` :677-700 · `test` :701-781 · `login` :782-877 · `_persist_browser_tokens` :878-893 · `_client_info_path` :894-915 · `logout` :916-930 · `token` :931-962 · `export_bridge` :963-1012 · `remove_bridge` :1013-1029 · `login_unified` :1030-1274 · `_login_unified_new` :1275-1337 · `_persist_me_cache` :1338-1356 · `_summary_with_me` :1357-1391 · `_detect_login_type` :1392-1415 · `_login_unified_relogin` :1416-1576 · `_login_unified_new_browser` :1577-1752 · `_login_unified_new_credential` :1753-1912 · `_resolve_project` :1913-2013 · `__all__` :2014-2028 | `packages/core/src/accounts/namespace.ts` (+ `login-unified.ts` for :1030-2013 if the file passes ~800 lines — R7 file conventions) |
| `session.py:1-79` (whole file) | `show` :24-32 · `use` :35-77 (mutual-exclusion guard :66-71; per-axis writes via ONE `apply_session` transaction :72-76) | `packages/core/src/accounts/session-namespace.ts` |
| `targets.py:1-99` (whole file) | `list` :25-31 · `add` :34-57 · `remove` :60-69 · `use` :72-81 · `show` :84-96 | `packages/core/src/accounts/targets-namespace.ts` |
| `_internal/auth/naming.py:1-133` (whole file) | `slugify` :40-83 · `default_account_name` :85-133 | `packages/core/src/accounts/naming.ts` |
| W1-D1 seam replacement (`b6-packets.md:1025`) | real `ResolverSeams` implementations over A2 + the effects bag | `packages/core/src/accounts/resolver-seams.ts` |

Python's namespaces are module-level functions building a fresh
`ConfigManager()` per call (`accounts.py:86-88`, `session.py:19-21`,
`targets.py:20-22`). TS core exports **factories** —
`createAccountsNamespace(effects)`, `createSessionNamespace(effects)`,
`createTargetsNamespace(effects)` — plus `defaultAuthEffects()` whose
effectful members throw (§3.2). B8 exports the ready-made `accounts` /
`session` / `targets` objects bound to on-disk effects, closing the four
deferred `__all__` names from the Phase-2 audit (playbook `:74-79`:
`accounts`/`session`/`targets`/`login_unified` → B7).

### §3.2 Seam enumeration — the normative B7-owns / B8-owns map

**W1-D1 `ResolverSeams` (5 members, defaults currently ALL throw
`UNPORTED_RESOLVER_SEAM` — `lifecycle.ts:111-143`). A1 replaces FOUR:**

| Seam (lifecycle.ts) | B7-A1 implementation | Status after B7 |
|---|---|---|
| `resolveSession({target})` | A2 `resolveSession({target}, sourcesFrom(effects))` | REAL |
| `getAccount(name)` | `effects.config.getAccount(name)` | REAL (over injected config; on-disk config itself is B8) |
| `resolveProjectAxis(args)` | A2 `resolveProjectAxis` over `effects.env` + args | REAL |
| `envWorkspaceId()` | A2 `envWorkspaceId(effects.env)` | REAL |
| `persistActive(session)` | routed to `effects.persistActive` (`ConfigManager.apply_session` twin, `workspace.py:696-722`) | **STAYS STUBBED** — B8-owned (`b6-packets.md:1026`: "B8 (config I/O) via B7 orchestration"). B7 ships the ROUTING; the effect member's default throws. |

Export: `resolverSeamsFromEffects(effects: AuthEffects): ResolverSeams` —
`Workspace` construction accepts it via the existing `WorkspaceOptions`
seam bag (no facade signature change; the B6 tests that stub seams keep
working).

**`AuthEffects` — the B7-defined interface bag for every node effect in
`accounts.py`/`session.py`/`targets.py`. B8 implements; B7 ships
`defaultAuthEffects()` where each unimplemented member throws
`MixpanelHeadlessError` code `UNPORTED_AUTH_SEAM` with `{seam: name}` and a
`TODO(port): B8` marker (the W1 `unportedSeam` pattern, `lifecycle.ts:111-122`):**

| Effects member | Python counterpart | Owner of the real impl |
|---|---|---|
| `config: ResolverConfigSource & ConfigWrites` — `ConfigWrites` = `addAccount`/`updateAccount`/`removeAccount`/`listAccounts`/`setActive`/`applySession`/`applyTarget`/`addTarget`/`removeTarget`/`listTargets` | `ConfigManager` (`_internal/config.py`) | **B8-N1** |
| `env: ResolverEnv & { get(name: string): string \| undefined }` (the token_env + `MP_USERNAME`/`MP_SECRET` login-detect reads, `accounts.py:1409`, `region_probe.py:252`) | `os.environ` | **B8** (process.env) |
| `tokenStore: { readTokens(name): OAuthTokens \| null; writeTokens(name, tokens): void; removeAccountDir(name): void; clientInfoExists(region): boolean }` | `ensure_account_dir`/`atomic_write_bytes`/`_safe_rmtree_warn`/`_client_info_path` (`accounts.py:878-915`, :278-303; `auth/storage.py`) | **B8-N2** |
| `tokenResolver: TokenResolver` | `OnDiskTokenResolver` (`token_resolver.py:57-288`) | **B8-N2** (B7 tests inject the `_FreshBrowserBearer` twin, `accounts.py:91-128`) |
| `oauthFlow: { login(region, openBrowser): Promise<OAuthTokens> }` | `OAuthFlow.login` (`flow.py`) | **B8-N3** |
| `bridge: { load(): BridgeView \| null; export(opts): string; remove(at): boolean }` | `bridge.py` `load_bridge`/`export_bridge`/`remove_bridge` | **B8-N2** |
| `meCacheStore: MeCacheStore` (on-disk) | `MeCache` (`me.py:413-607`; `_persist_me_cache` `accounts.py:1338-1356`) | **B8-N2** (in-memory default from W1's `services/me.ts` used meanwhile) |
| `fetchImpl: typeof fetch` + `now(): number` | httpx / clock (token-expiry checks, `/me` probes) | injected everywhere already (R2.4/D1.4) — CORE, no stub |

**The named still-stubbed list after B7** (verbatim, goes into the code as a
committed constant `UNPORTED_AUTH_SEAMS` next to `defaultAuthEffects` so the
B8 packet consumes it by name): `persistActive` (via `config.applySession`),
`config.*` on-disk writes/reads, `env` (process.env wiring),
`tokenStore.*`, `tokenResolver` (on-disk), `oauthFlow.login`, `bridge.*`,
`meCacheStore` (on-disk). Everything else in the three namespaces runs REAL
in B7 under injected fakes — the namespace logic itself (guards, precedence,
name derivation, relogin state machine, region mismatch check, summary
assembly) is pure over the bag.

### §3.3 Behavior locks the shard must keep (branch-level)

- `session.use` / `targets.use` guard + atomicity: target mutually exclusive
  with axis kwargs (`session.py:66-71` — same `WS1_TARGET_MUTUALLY_EXCLUSIVE`
  coded twin as §2.2); ALL writes in ONE `applySession`/`applyTarget`
  transaction (`session.py:72-76`; `targets.py:72-81`) — never two effect
  calls where Python makes one.
- `accounts.use(name)` clears the workspace axis (042 semantics — verify
  against `accounts.py:651-676` before implementing; the docstring is the
  contract source).
- `accounts.add`: XOR `token`/`token_env` (model-level, already ported);
  per-type required-field guards; `derive_name=True` path calls `_fetch_me`
  + `default_account_name` (`accounts.py:361-492`, :493-589); name-collision
  suffixing lives in `naming.py`, never re-derived (R10.8).
- `login_unified` orchestration (`accounts.py:1030-1274`): auth-type
  detection env-driven (`_detect_login_type` :1392-1415 — `MP_USERNAME`+
  `MP_SECRET` → SA; `MP_OAUTH_TOKEN` → oauth_token; else browser); SA /
  oauth_token region: explicit `region=` skips the probe, else
  `probeRegionForCredential` (A2); browser defaults `us`; relogin vs new
  detection :1416-1576; project pick via `_resolve_project` :1913-2013
  (picker sort order locked by `TestLoginUnifiedPickerSortOrder` :1544);
  me-cache write :1338-1356 (through `meCacheStore`); progress hook
  invocations :1358+ (injected `ProgressFactory` — port as
  `(msg: string) => Disposable`-style callback, JSDoc the mapping).
- `accounts.login` region cross-check (`_assert_project_region_matches`
  :201-241 + `test_login_region_check.py`): picked project's `/me` domain
  region must equal the account's auth region → ConfigError (E-2) —
  `_domain_to_region` table :304-351 ports verbatim.
- `accounts.token()`: browser → resolver refresh path; oauth_token → static;
  SA → `None` (`accounts.py:931-962`) — through the injected
  `tokenResolver`, per-request semantics preserved (R2.9).
- `accounts.test()`: `/me` probe over the REAL client construction with the
  account's auth header; failure taxonomy via `_build_test_failure_result`
  :242-277 (codes, not messages).
- Secret discipline EVERYWHERE (pair-B lens, §5): `Secret` values never
  reach `JSON.stringify` output, error `details`, or thrown messages; the
  ONLY reveal sites are header construction and designated store writes —
  enumerate each reveal call in the shard notes (the SecretStr
  `get_secret_value` sites in the Python ranges above are the allowed list).

### §3.4 Layer-3 translation scope (A1) — incl. every B6 ledger split

| Python source | A1 takes | Notes / TS file |
|---|---|---|
| `tests/unit/test_accounts_namespace.py` (1,685 lines, 62 tests) | ALL 17 classes: `TestAdd` :46, `TestUpdate` :243, `TestList` :277, `TestUse` :299, `TestShow` :349, `TestRemove` :384, `TestToken` :416, `TestTest` :451, `TestTestOAuthBrowser` :614, `TestLogin` :756, `TestPublicSurface` :914, `TestLogoutHonorsStorageOverride` :934, `TestSummaryTableDynamicWidth` :967, `TestLoginUnifiedActivation` :993, `TestLoginUnifiedMeCacheWrite` :1137, `TestLoginUnifiedFlagValidation` :1228, `TestLoginUnifiedSummaryFields` :1285, `TestLoginUnifiedProgressHook` :1358, `TestLoginUnifiedPickerSortOrder` :1544 | `test/accounts/accounts-namespace.test.ts` + `test/accounts/login-unified.test.ts`; on-disk fixtures (tmp `$HOME`, tokens.json) re-express over injected `tokenStore`/`config` fakes, header-cited |
| `tests/unit/test_session_namespace.py` (116 lines) | `TestShow` :42, `TestUse` :59 | `test/accounts/session-namespace.test.ts` |
| `tests/unit/test_targets_namespace.py` (158 lines) | `TestAdd` :42, `TestTargetWorkspaceValidation` :62, `TestList` :98, `TestUse` :113, `TestRemove` :136, `TestShow` :151 | `test/accounts/targets-namespace.test.ts` |
| `tests/unit/test_login_region_check.py` (196 lines, 4 tests) | `TestLoginRegionMismatch` :84 | `test/accounts/login-region-check.test.ts` |
| `tests/unit/test_naming.py` (153 lines) + `tests/pbt/test_naming_pbt.py` (154 lines, 8 properties) | `TestSlugify` :24, `TestDefaultAccountName` :100; PBT: idempotence :45, charset :53, no edge dashes :63, no double dash :72, uniqueness vs existing :101, determinism :110, suffix-starts-at-2 :120, suffix monotonic :136 — same strategy shapes | `test/accounts/naming.test.ts`, `naming.pbt.test.ts` |
| `tests/unit/test_workspace_use.py` (B6 ledger `:1029`; deferral header in `test/workspace/workspace-use.test.ts:7-27`) | `TestUseAccount` :89, `TestPersist` :190, `TestUseAccountEnvVarPriority` :221, `TestUseTargetEnvOverride` :346, `TestUseAccountWorkspaceEnvValidation` :384, PLUS the four seam-bound cases W1 deferred inside its own classes: `TestTargetMutualExclusion::test_target_alone_applies_three_axes` :176, `TestUseUpdatesSessionAndClearsCaches::test_use_target_also_clears_caches` :301, `::test_use_account_updates_me_cache_account_name` :311, `::test_use_target_updates_me_cache_account_name` :333 | extend `test/workspace/workspace-use.test.ts` (drop the DEFERRED header rows as they land — the header must end up listing ZERO B7 deferrals) |
| `tests/unit/test_workspace_init.py` (B6 ledger `:1030`) | `TestActiveResolution` :66, `TestExplicitOverrides` :76, `TestTarget` :96 (constructor resolution through the now-real seams; the constructor's own WS1 twin `workspace.py:455-465` is A1's to port) | extend `test/workspace/workspace-init.test.ts`; `TestBridgeTokenMaterialization` :167 stays **B8** |
| `tests/unit/test_workspace.py` (B6 ledger `:1031`) | `TestCredentialResolution` :96 | extend `test/workspace/workspace-facade.test.ts` (remove its :9 deferral header row) |
| `tests/unit/test_042_edge_cases.py` (B6 ledger `:1032`) | `TestSecretLeakage` :615-681 — WHOLE class (all cases are library-level repr/str/error-payload redaction; the on-disk token-materialization case re-expresses over the injected `tokenResolver` fake, header-cited). **`TestCliExitCodes` :550-614 — EXCLUDED, decision recorded**: plan D4 defers the CLI (and its ~670 CLI Layer-3 lines, plan `:101`) out of the port; the class drives `CliRunner` exit codes with no library assertion to preserve. Documented here + in the A1 notes file, not silently dropped. | `test/accounts/secret-redaction.test.ts` |
| `tests/unit/test_workspace_oauth.py` (274 lines; playbook B7 row `:231`) | `TestWorkspaceConstructionWithOAuth` :157, `TestWorkspaceListWorkspaces` :196, `TestWorkspaceResolveWorkspaceId` :253 (session-bypass construction + injected token resolver — no B8 dependency) | `test/workspace/workspace-oauth.test.ts` |
| `tests/unit/test_workspace_resolution.py` residue (playbook B7 row `:230`) | `TestMeServiceResolveWorkspace` :154 (against core `MeService` + in-memory `MeCacheStore` — the B4-C1 header note "is B8" at `test/client/client-workspace.test.ts:12` is STALE post-W1; correct it in place) and `TestFacadeResolverWiring` :611 (the dagger vector's Layer-3 twin — facade installs `setWorkspaceResolver` and resolution succeeds without a public call; the class was assigned "B6" by the same stale header but has NO TS translation — verified by grep 2026-08-16; it lands HERE, gap closed) | extend `test/services/me-service.test.ts` + `test/workspace/workspace-facade.test.ts` |

### §3.5 R10.10 consumers (signatures pasted)

End users are the consumers (playbook B6-row precedent): the Python
signatures ARE the options-bag contract (R3.3/R3.8 — kwonly → one options
bag, Python spelling on wire-shaped keys; camelCase acceptable for pure
config args per the B6 Caution-6 precedent, decide per-function and record).
Pasted from HEAD:

```python
accounts.list() -> list[AccountSummary]
accounts.add(name=None, *, type, region=None, default_project=None,
             username=None, secret=None, token=None, token_env=None,
             derive_name=False) -> AccountSummary
accounts.update(name, *, region=None, default_project=None, username=None,
                secret=None, token=None, token_env=None) -> AccountSummary
accounts.remove(name, *, force=False) -> list[str]
accounts.use(name) -> None
accounts.show(name=None) -> AccountSummary
accounts.test(name=None) -> AccountTestResult
accounts.login(name, *, open_browser=True) -> OAuthLoginResult
accounts.logout(name) -> None
accounts.token(name=None) -> str | None
accounts.export_bridge(*, to, account=None, project=None, workspace=None) -> Path
accounts.remove_bridge(*, at=None) -> bool
accounts.login_unified(*, name=None, region=None, project=None,
    account_type=None, no_browser=False, secret_stdin=False, token_env=None,
    service_account=False, project_picker=None, progress=None) -> AccountSummary
session.show() -> ActiveSession
session.use(*, account=None, project=None, workspace=None, target=None) -> None
targets.list() -> list[Target];  targets.add(name, *, account, project,
    workspace=None) -> Target;  targets.remove(name) -> None
targets.use(name) -> None;  targets.show(name) -> Target
```

Result types already live in TS (`types/entities/accounts.ts:57`
`AccountSummary`, :160 `AccountTestResult`, :265 `Target`, :356
`OAuthLoginResult`). Internal consumers: `Workspace` constructor/`use()`
via `resolverSeamsFromEffects`; B8 packet consumes `AuthEffects` +
`UNPORTED_AUTH_SEAMS` by name; the doubled-review pair B consumes the §3.3
reveal-site allowlist.

### §3.6 R10.9 harness spec — `throwaway/b7-a1/`

Same posture as §2.6 (no oracle bridge — local model + edge set):

1. **Every A1-local error branch**, enumerated from the registry code
   families used in the ranges above: unknown account (`AccountNotFoundError`),
   duplicate add (`AccountExistsError`), remove-active guard/`force`
   (`AccountInUseError` — verify against :633-650), add/update XOR and
   missing-field ConfigErrors, `login` on a non-browser account, region
   mismatch E-2, `login_unified` flag-validation matrix
   (`TestLoginUnifiedFlagValidation` :1228 is the enumeration source),
   unknown target, target-with-deleted-account, `session.use`/`targets.use`
   guard, every `UNPORTED_AUTH_SEAM` default (call each stubbed member,
   assert code + `details.seam`), every `UNPORTED_RESOLVER_SEAM` that
   REMAINS (exactly one: `persistActive` routing when B8 absent).
2. **login_unified state machine sweep**: detect ×3 (env-SA / env-OT /
   browser default) × relogin/new × region explicit/probed × project
   explicit/picked/single/none — driven through injected fakes; picker sort
   order and progress-hook call sequence asserted.
3. **Mandatory edge set** through every annotation-admitting param (account
   names at the 1/64-char boundaries, `"𝒳"` in org names through slugify,
   empty strings, `18.0`/`1.5` where numbers are admitted — workspace ids).
4. **Secret-redaction sweep** (feeds pair B): construct SA/OT/browser
   accounts with sentinel secrets, drive EVERY error branch from item 1,
   assert the sentinel appears in no thrown message, no `details` JSON, no
   RUN-record line, no fake-store write outside the designated token writes.
5. fast-check: ≥500 examples over namespace op sequences against an
   in-memory model of config state (add/use/remove/target invariants:
   active-account consistency, workspace-clear-on-account-switch, target
   atomicity). Seeds + counts → `context/phase3/notes/B7-A1-notes.md`.

### §3.7 Done-criteria (A1)

`accounts/` module files + `resolver-seams.ts` + `defaultAuthEffects` +
`UNPORTED_AUTH_SEAMS` on disk; the four seams REAL (a `Workspace` built with
`resolverSeamsFromEffects(fakeEffects)` passes the previously-deferred
`use(account=…)`/`use(target=…)`/env-priority Layer-3); all §3.4 files green
incl. the de-deferred B6 classes (headers updated to zero B7 rows);
`tsc --strict` + `npm run check` green; lint boundary green; harness RUN
record written; JSDoc complete; one local TS commit; notes committed in the
Python repo. NO vectors (0 owned) — Layer-3 is the lock.

---

## §4 Gate flip spec (P3-2e, one fable task after both shards + doubled reviews)

1. **Flip**: `batch-status.ts` appends `["region_probe.", "done"]` (playbook
   P3-5 §4 B7 row `:663`). Standing collision assertion: scan all corpus api
   names — the only name matching the new prefix is
   `region_probe.probe_region` (14 vectors); the only remaining pending name
   is `oauth_flow.refresh_tokens` (7). Zero collisions expected; record the
   scan in the gate notes.
2. **Report checkpoint**: `npm run conformance` → **3,244 PASS / 0 FAIL /
   7 UNPORTED** (UNPORTED drops by exactly 14 — the B7 gate delta; no †
   adjustment, §1). Archive JSON →
   `context/phase3/reports/2026-08-XX-b7-gate.json` (Python repo, support
   branch, docs commit).
3. **Anchor re-pins (rig test duty)**: `runner.test.ts:135-157` and
   `batch-status.test.ts:87,240-243` use `region_probe.probe_region` as the
   pending-name exemplar ("pending until B7 by construction") — re-anchor
   both to `oauth_flow.refresh_tokens` in the flip commit (the B6-gate
   precedent, `b6-packets.md:1016`); the pattern RETIRES at the B8 gate
   (`b6-packets.md:1033`).
4. **Oracle probe**: `region_probe.probe_region` is a WIRE api name — exempt
   from the mechanical oracle probe (playbook P3-2e item 3). No new oracle
   families exist for B7 (auth has no oracle surface); the differential
   full-suite regression still runs over the EXISTING registered surface,
   fresh seeds, ≥500/family, RUN appended to `differential/oracle/RUN.md`.
5. **Checks**: `npm run check` green (TS); `just check` green if any Python
   file changed (docs/notes-only commits expected). No referees (B7 touches
   no bookmarks).
6. **Cleanup + notes**: remove `throwaway/b7-a1/`, `throwaway/b7-a2/` after
   arbiter sign-off; finalize `context/phase3/notes/B7-notes.md` (RUN
   records, findings, the §6 disclosure decisions, escalations); gate commit
   on TS `main`, docs/report commit on the Python support branch.

---

## §5 DOUBLED-REVIEW protocol (P3-3 auth doubling — binding for both shards)

Per SHARD: **two independent review pairs (4 reviewers) + 1 arbiter**, all
fable. Every reviewer runs the standard P3-2(d) items 1–5 (R10.2
assertion-weakening diff, rulebook pass, GATE-R5 grep where wire-adjacent,
`TODO(port)` triage, harness re-run from recorded seeds). Lenses:

- **Pair A (primary)** — A-lens-1 *resolver/probe semantics*: line-by-line
  diff of `resolver.ts`/`region-probe.ts`/`namespace.ts` against the Python
  ranges in §2.1/§3.1 — branch order, env falsiness, SA-quad-over-OT,
  short-circuit + close-in-finally, `all([])` edge, cpSlice cap, attempts
  mirroring/tuple shapes, transaction atomicity, login_unified state
  machine. A-lens-2 *assertion fidelity + coverage*: the R10.2 diff over
  every §2.4/§3.4 file, header-exclusion audit (every deferred/excluded
  class carries a citation to this packet or plan D4), test-count
  reconciliation vs the Python `def test_` counts, harness RUN reproduction.
- **Pair B (BLIND)** — B-lens-1 *credential-safety*: Secret leakage (grep
  every new file + test + RUN record for reveal sites; diff against the
  §3.3 allowlist; error `details`/`toDict` payloads; the §3.6-item-4 sweep
  re-run), header construction (Basic = base64 over UTF-8 bytes — the btoa
  trap; Bearer prefix exact; headers never echoed into errors/attempts),
  redaction discipline (SecretStr twins in every new type; no secret in
  `JSON.stringify` of any result/summary). B-lens-2 *adversarial end-to-end
  auth scenarios*: hostile inputs driven through the REAL surfaces —
  malformed/oversized probe bodies at the cap boundary, unicode + Nd-digit
  env values, `token_env` indirection abuse, bridge-vs-config account
  confusion, precedence-bypass attempts across all three axes, seam-stub
  probing (every UNPORTED default), replay of the 14 vectors from scratch.

**Independence rule (file-access, NAMED)**: pair B receives ONLY the Python
sources + the TS diff (playbook `:383-385`). Pair B agents MUST NOT read
`context/phase3/design/b7-review-pairA-semantics.md`,
`context/phase3/design/b7-review-pairA-fidelity.md`, the shard notes'
review sections, or any arbiter draft; their task packets omit those paths
and state the prohibition. Output files: pair A →
`b7-review-pairA-{semantics,fidelity}.md`; pair B →
`b7-review-pairB-{credsafety,adversarial}.md`; the ARBITER is the only
reader of all four (`b7-review-resolution.md`). A pair-B output that cites
a pair-A file is void — the orchestrator re-runs that reviewer fresh.
Sequencing tip: launch pair B first or concurrently so pair-A output cannot
exist in the repo when pair B starts.

---

## §6 Cautions (file:line cited)

1. **Env falsiness**: `""` = absent at `resolver.py:71,97,123,205,239` and
   `region_probe.py:253` — watchlist #6; never `!v` on the workspace int.
2. **Invalid `MP_REGION` aborts even with a lower-rung winner**
   (`resolver.py:73-78` reached via :96/:122 before :167) — port the raise
   position exactly.
3. **SA quad > OAuth-token env; partial quad falls through silently**
   (`resolver.py:161-166`, :97-98; PR #125).
4. **`isdigit` vs `pythonInt`**: `MP_PROJECT_ID` guard is `str.isdigit()`
   (`resolver.py:207`) — NOT the `int()` grammar; `MP_WORKSPACE_ID` IS
   `int()` (`resolver.py:242`) → `pythonInt` (R11.7). Two different parsers
   three lines apart; do not unify.
5. **Attempts tuple shapes differ**: success attempts 2-tuples, failure
   attempts 3-tuples (`region_probe.py:142-143`); the success return mirrors
   failures WITHOUT bodies (:163-166).
6. **`close()` in finally, all paths** (`region_probe.py:174-175`) — the 200
   path closes before returning.
7. **Body cap is a codepoint slice** (`region_probe.py:171`) → `cpSlice(text,
   0, 4096)` (R11.6); harness pins the surrogate-straddle at 4096.
8. **Network-error rendering needs the code→httpx-class reverse table**
   (`region_probe.py:156` vs `transport-errors.ts:82-86` — ConnectError's
   `causeName` is `"Error"`; only `cause.code` recovers the class). Vector-
   locked for `ECONNREFUSED` only; rest is principled best-effort, disclosed
   in the RUN record.
9. **`all([])` is True**: `order=()` raises `RegionProbeNetworkError` with
   empty attempts (`region_probe.py:182-187`).
10. **Basic-auth bytes**: `f"{u}:{s}".encode()` is UTF-8
    (`region_probe.py:246-247`) — `TextEncoder`, never `btoa` on a UTF-16
    string (silent mojibake for non-ASCII secrets). Pair-B item.
11. **`probeBaseUrl`**: `urlsplit`→`urlunsplit` scheme+host only
    (`region_probe.py:276-277`); Layer-3 locks trailing-slash + future-path
    shapes (`test_region_probe.py:379-486`). URL PARSING here is read-only
    and allowed; R2.13's concat rule still governs request-path assembly.
12. **`slugify` Unicode skew**: NFKD + ASCII-fold (`naming.py:76-78`) runs on
    V8's Unicode tables (17) vs pinned CPython 16 — no pinned table is
    feasible for full NFKD; document the skew (TS-2 caveat style), bias the
    naming fuzz domain to ASCII/Latin-1/ligatures, disclose residuals.
    Truncation `dashed[:32]` (:83) is safe post-fold (pure ASCII by then) —
    assert that invariant in a test rather than importing cpSlice.
13. **`default_account_name` first-org pick is INSERTION order**
    (`naming.py:124` `next(iter(...))`) but TS `MeResponse.organizations` is
    a plain `Record` with integer-like org-id keys (`client/me.ts:390`) — JS
    hoists integer-like keys ascending (the Discrepancy #9/#10 mechanism at
    a NEW site). Divergence whenever `/me` emits orgs out of ascending-id
    order. The A1 implementer must NOT self-sanction: disclose in the RUN
    record and escalate to the shard arbiter for a #9/#10-style ruling
    (options: unreachable-in-practice note, fuzz-domain exclusion, or an
    ordered container change — arbiter's call, user ratification if a
    comparison relaxation is proposed).
14. **Coded errors, not minted ones**: the target-exclusivity guards
    (`resolver.py:400-405`, `session.py:66-71`, constructor twin
    `workspace.py:455-465`) all reuse `WS1_TARGET_MUTUALLY_EXCLUSIVE`
    (`lifecycle.ts:191`); resolver axis failures are `ConfigError`s with the
    FR-024 texts (`resolver.py:318-359`) — codes are the contract (R5),
    texts ported but never vector-asserted.
15. **R2.9 per-request auth**: `accounts.test()`/`token()` and every client
    the shard constructs resolve the bearer at REQUEST time through
    `TokenResolver` (`auth/session.ts:378` `sessionAuthHeader`) — never
    capture a header at construction. Grep-audited at review.
16. **Watchlist #13**: any `isinstance(x, dict)` in these ranges (e.g. `/me`
    payload handling in `_fetch_me` :150-200) ports via the ONE canonical
    guard — import `isPythonDict` (`compat/python-dict.ts`) or
    `isPlainRecord` (`client/internals.ts`) per the B6-ARB standing rule;
    a new local helper is a per-se finding.
17. **Stale header notes**: `test/client/client-workspace.test.ts:12-15`
    says `TestMeServiceResolveWorkspace` "is B8" and `TestFacadeResolverWiring`
    "is B6" — both land at B7-A1 (§3.4); correct the header in the same
    commit that translates them.
18. **Deferral headers must zero out**: `workspace-use.test.ts:7-27`,
    `workspace-init.test.ts`, `workspace-facade.test.ts:9` list "→ B7" rows;
    after A1 those headers must list NO remaining B7 deferrals (B8-only rows
    stay, e.g. `TestBridgeTokenMaterialization`).
19. **No mutation testing** `[SA1]`; **no real network** anywhere (Phase-4
    owns live auth scenarios); `~/.mp` is NEVER touched by tests — all
    storage is injected fakes (the Python suites' tmp-`$HOME` fixtures
    translate to in-memory stores, header-cited).

## §7 Deferral ledger

### Inbound (all placed)

| Inbound deferral (source) | Placed |
|---|---|
| `ResolverSeams` UNPORTED defaults — 4 real impls (`b6-packets.md:1025`) | A1 §3.2 |
| `persistActive` via B7 orchestration (`b6-packets.md:1026`) | A1 §3.2 (routing only; impl B8) |
| `test_workspace_use.py` resolver classes (`b6-packets.md:1029`) | A1 §3.4 |
| `test_workspace_init.py` resolver classes (`b6-packets.md:1030`) | A1 §3.4 (`TestBridgeTokenMaterialization` → stays B8) |
| `test_workspace.py::TestCredentialResolution` (`b6-packets.md:1031`) | A1 §3.4 |
| `test_042_edge_cases.py` 4 B7 classes + the 2 author-decides classes (`b6-packets.md:1032`) | A2 §2.4 (4 classes) + A1 §3.4 (`TestSecretLeakage` taken; `TestCliExitCodes` EXCLUDED per plan D4 — decision recorded §3.4) |
| UNPORTED-probe re-anchor duty (`b6-packets.md:1016` pattern) | Gate §4.3 |
| Playbook B7 Layer-3 row files (`:227-231`) | §2.4 + §3.4 (incl. the two `test_workspace_resolution.py` residue classes the stale B4-C1 header orphaned) |

### Outbound (created by B7, for the B8 packet author)

| Outbound deferral | Owner |
|---|---|
| `UNPORTED_AUTH_SEAMS` implementations: `config` on-disk (TOML), `env` (process.env), `tokenStore`, on-disk `TokenResolver`, `oauthFlow.login`, `bridge.*`, on-disk `meCacheStore`, `persistActive` (`applySession`) | B8 (N1/N2/N3 per playbook `:769-772`) |
| Node-level default wiring: ready-made `accounts`/`session`/`targets` exports + `ResolverSources` built from process.env + ConfigManager + `load_bridge` | B8 |
| `test_workspace_init.py::TestBridgeTokenMaterialization` :167 | B8-N2 |
| `test_042_edge_cases.py::{TestTokenResolverMalformed :240, TestBridgeEdgeCases :394, TestConfigManagerEdgeCases :459}` | B8 (per `b6-packets.md:1032`) |
| UNPORTED-probe pattern retirement at the LAST flip | B8 gate (`b6-packets.md:1033`) |
| Caution #13 arbiter ruling follow-through (if it lands as a disclosed divergence, the B8/Phase-4 re-examine trigger goes into the playbook discrepancy log) | B7 arbiter → playbook |

---

**Done for this packet (task B7-DL)**: 14/14 vectors accounted (§1, §2.3);
seams enumerated B7-vs-B8 with the named still-stubbed list (§3.2); binding
plan + gate flip spec (§2.7, §4); doubled-review protocol with the file-
access rule (§5); cautions cited (§6).

