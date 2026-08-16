# B6-W1 notes — lifecycle & construction + workspace management + /me trio + business context + the B5 §8 veneers

Status: **DONE**. Packet: `context/phase3/design/b6-packets.md` §3
(spec of record: `phase3-playbook.md` v1.1). Tier: opus.

## §0 Inventory (start of shard)

- TS repo HEAD at start: `44734be` (B5 gate cleanup). `workspace.ts` =
  2,606 lines, B6 marker at `:2509`.
- Stubs replaced: `use()` `:702`, `close()` `:718`,
  `[Symbol.asyncDispose]` `:736` (all three threw `UNPORTED_MEMBER`).
- Already live and COMPOSED, never re-implemented (R10.8):
  `client.use` / `close` / `setWorkspaceResolver` / `hasWorkspaceResolver`
  (`client.ts:1019/1208/1114/1109`), `client.me` / `listWorkspaces` /
  `resolveWorkspaceId`, `client/me.ts` models + `selectWorkspaceId` +
  `workspaceViewFromMeWorkspace`, `services/entities/business-context.ts`,
  the B4-C2 `streamEvents`/`streamProfiles` helpers
  (`services/queries/streaming.ts:708,744`) and `validateLimit` (`:154`).
- No prior W1 work on disk (`workspace-members/` and `services/me.ts`
  did not exist).

## §1 Files landed

| file | role |
| --- | --- |
| `packages/core/src/services/me.ts` (NEW) | `MeService` (`me.py:609-915`) + the `MeCacheStore` seam + `inMemoryMeCache` default |
| `packages/core/src/workspace-members/lifecycle.ts` (NEW dir + file) | `ResolverSeams` (W1-D1), the WS1 guard, the business-context member bodies + `_validate_level` / `_require_str_field` / `_resolve_organization_id` / `_cached_organization_id` |
| `packages/core/src/workspace.ts` | `session` field → getter; `#meService` / `#accountName` / `#seams` / `#meCacheFactory`; resolver wiring; `use()` / `close()` / `[Symbol.asyncDispose]`; the B6-W1 append-only section (15 members + 3 veneers) |
| `packages/core/src/types/entities/model-base.ts` | `modelDumpExcludeNone()` (W1-D4) + `dumpExcludeNoneValue` |
| `packages/core/src/types/entities/business-context.ts` | `is_empty` / `character_count` ACCESSORS (the Python `@computed_field` properties; `computedSpecs` already carried the serializer half) |

Layer-3: `test/workspace/workspace-facade.test.ts`,
`workspace-use.test.ts`, `workspace-init.test.ts`,
`workspace-streaming.test.ts`, `business-context.test.ts`,
`test/services/me-service.test.ts`, plus two appended classes in
`test/workspace/facade-scoping.test.ts`.

Touched B5 files (recorded so the review pair sees them):
`test/workspace/discovery-facade.test.ts` (its "B6-owned members refuse
with UNPORTED_MEMBER" case now asserts the LIVE pair),
`test/workspace/workspace-test-helpers.ts` +
`test/services/schema-graph.test.ts` (their client stubs gained
`hasWorkspaceResolver` / `setWorkspaceResolver` / `close`, which
`MagicMock(spec=MixpanelAPIClient)` auto-provides in Python).

## §2 Design decisions (arbiter-visible)

### W1-D1 — resolver seams

`ResolverSeams` = `resolveSession` / `getAccount` / `resolveProjectAxis`
/ `envWorkspaceId` / `persistActive`, injected through
`WorkspaceOptions.seams` (partial; missing members take the defaults).
Every default throws `MixpanelHeadlessError` code
`UNPORTED_RESOLVER_SEAM` with `details.seam` and a `TODO(port): B7`
marker. The shape is B7's inbound contract — consume it by name.

`use()` ports the guard + all three branches + the swap core in full;
only the resolution steps route through the seams. The
`_format_no_project_error` MESSAGE is a `TODO(port)` for B7 (class +
`ConfigError` is what W1 locks, R5.4).

### W1-D2 — `close()` vs the B5 `readonly client` (DECIDED: close in place)

Python nulls `_api_client`; `_get_api_client()` builds a REPLACEMENT and
re-applies `_initial_workspace_id` + the resolver. TS keeps the
`readonly client` the R6.2 identity assertions track and calls
`client.close()`, which drops the pool token; `ensureHttp()` re-opens on
the next request. Consequences, measured:

- `close()` is idempotent, `await using` works, post-close calls succeed
  (harness `err/close then reuse`).
- ONE divergence: Python's replacement client forgets a runtime
  `set_workspace_id()` pin (it re-applies `_initial_workspace_id`
  instead); the TS client keeps its current pin. No corpus vector calls
  `close()`, and no Layer-3 case covers pin-after-close.
  `#initialWorkspaceId` is therefore deliberately ABSENT from the facade
  (its only Python reader is the recreation arm) — noted inline at
  `workspace.ts:742`.

### W1-D3 — stream veneers (B5 §8 outbound deferral, CLOSED)

`streamEvents` / `streamProfiles` are `async *` members that `yield*`
the B4-C2 helpers (R6.6, item-level), returning `AsyncGenerator`
directly (R3.2). They stay PROJECT-scoped even with a pinned workspace
(locked by an additive case at the end of `workspace-streaming.test.ts`;
Python contract at `workspace.py:566-573`). `get api()` returns
`this.client`.

### W1-D4 — `modelDumpExcludeNone()` (W2–W8 consume by name)

Landed on `EntityModel`. Pydantic v2 semantics MEASURED
(`uv run python`, 2026-08-16): declared fields + extras + computed
fields all participate; `None` drops at every model level; nested models
recurse; lists map element-wise (nothing dropped); **plain dict values
KEEP their `None`s**; datetimes render as ISO text. `toJSON()` is not a
substitute (it keeps `None` → `null`).

### MeService (§3.3) + the dagger wiring

`MeService` ports `me.py:609-915` with the cache injected as
`MeCacheStore` (`accountName` / `get` / `put` / `invalidate`, each
allowed to return a promise so B8-N2's on-disk twin fits unchanged).
`packages/core` ships `inMemoryMeCache`. `peek()` is async (the store
may be).

The facade installs
`client.setWorkspaceResolver(pid => this.meService.resolveWorkspace(pid))`
at construction and re-asserts it after every `use()`; the closure reads
the CURRENT service, so the Python `lambda pid: self._me_svc…` semantics
(re-created service, same lambda) survive. A resolver already installed
on an INJECTED client is left alone (`workspace.py:789-791`). This is
the wiring the B4 dagger vector measures (resolve from the warm `/me`
WITHOUT a `/workspaces/public` call) — harness check
`equiv/resolve_workspace_id (me-resolver)` proves it costs exactly one
wire call.

## §3 Layer-3 translation ledger

| Python source | Translated here | Deferred (owner, header-cited in the TS file) |
| --- | --- | --- |
| `test_workspace.py` | `TestLiveQueries`, `TestDiscovery`, `TestContextManager`, `TestLimitValidation`, `TestWorkspacesMethod`, `TestProjectsMethod`, `TestCodedWorkspaceGuardCodes` (use-arm) | `TestCredentialResolution` (empty in Python) → B7; the three CONSTRUCTOR-guard cases (`:969`, `:975`, `:1021`) → B7 (§14 Caution 4) |
| `test_workspace_use.py` | `TestUseWorkspace`, `TestUseProject`, `TestHTTPTransportPreservation`, `TestTargetMutualExclusion`, `TestUseUpdatesSessionAndClearsCaches` | `TestUseAccount`, `TestPersist`, `TestUseAccountEnvVarPriority`, `TestUseTargetEnvOverride`, `TestUseAccountWorkspaceEnvValidation` → B7. Seam-bound cases inside the W1 classes (`:176`, `:301`, `:311`, `:333`) run against stubbed seams |
| `test_workspace_init.py` | `TestSessionBypass`, `TestReadOnlyProperties` | `TestActiveResolution` / `TestExplicitOverrides` / `TestTarget` → B7; `TestBridgeTokenMaterialization` → B8 |
| `test_workspace_streaming.py` | WHOLE (6 classes, 20 cases) | — |
| `test_workspace_business_context.py` | WHOLE (6 classes, 20 cases) | — |
| `test_query_workspace_scoping.py` | `TestWorkspaceFacadeScoping` + `TestDiscoveryCacheAcrossUse` (the B5 §8 inbound deferrals) | — |
| `test_me.py::TestMeService` | WHOLE (ADDITION — the packet's §3 table does not name `test_me.py`, but W1 owns the class it tests) | `TestMeCache`, `TestMeCacheConcurrency`, `TestMeCacheSymlinkRejection` → B8-N2 |
| `test_042_edge_cases.py` | NONE (packet §14 Caution 1 — playbook misassignment) | B7 / B8 per §13 |

Translation notes worth the review pair's attention:

- `TestContextManager::test_context_manager_enter_returns_self` has no
  TS twin object to compare (there is no `__enter__` return value); it
  translates to "disposal runs `close()` on this instance" plus the
  idempotency case.
- Normalized `event_time` is a `datetime` in Python and UTC ISO TEXT in
  TS (`transforms.ts:443`); `isinstance(..., datetime)` +
  `tzinfo == utc` translate to the exact spelling
  `2024-01-15T14:20:00+00:00`.
- `stream_profiles`' Python assertion is the FULL kwargs bag (all-None
  keys included); TS omits absent keys (R3.9), so the equivalent lock is
  `exportProfilesCalls === [{}]` / `[{where}]` — "no filter key was
  invented".

## §4 R10.9 harness RUN record (`throwaway/b6-w1/`)

Facade harness only — W1's members have no oracle-call surface, so there
is no differential half (packet §3). Deterministic, no seed.

```
npx vite-node throwaway/b6-w1/wire-edges.ts
checks 61   failures 0
```

| group | checks |
| --- | ---: |
| (i) delegation equivalence (`list_workspaces`, `resolve_workspace_id` ×2, `me`, the four business-context members) | 12 |
| (ii) wire status branches (`me` 200/401/403 + SA-403 wording; `set_business_context` 200/400/429-exhausted; `list_workspaces` 200-empty/500) | 11 |
| (iii) mandatory edge set `18.0, 1.5, true, null, [], "", "𝒳"` × `use(workspace=)`, `set_business_context(content)`, `organization_id` | 21 |
| (iv) every W1-local error branch (WS1 ×3, all five seams, no-project `ConfigError`, me-403 through org resolution, `_require_str_field` ×2, WS2, `BUSINESS_CONTEXT_TOO_LONG`, close-idempotency + reuse) + the R6.2 identity check | 17 |

**Defect found and fixed by the harness**: `MeService.fetch()` fed the
LOSSLESS response tree to `MeResponse.fromDict`, so
`MeProjectInfo.organization_id` failed `coerceInt` with "Expected int,
got object". Python validates the plain `json.loads` output
(`me.py:762`). Fixed with `toNativeJson(...)`, the same normalization
every B4 model site performs (`client.ts:879`). The Layer-3 suites could
not catch it — their payloads are plain objects, exactly like the Python
fixtures.

**Recorded, not defects** (Discrepancy #8 boundary; Python measured
2026-08-16):

- `organization_id=True`: pydantic accepts it (bool subclasses int), the
  port raises — the ratified port-wide rule **R4.12** (`coerce.ts:121`),
  not a W1 choice.
- `use({workspace: 1.5 / "" / []})`: Python's `WorkspaceRef` is a
  Pydantic model and raises on construction; TS's is a plain interface,
  so the value rides through to the client. Both are out of the declared
  `int | None` annotation → unspecified per #8.
- `18.0` behaves as the integral `18` on both sides; `1.5`, `""`, `[]`,
  `"𝒳"` raise on both sides for `organization_id`.

## §5 Deferrals emitted (for the B6 §13 ledger / B7 + B8 packets)

1. `ResolverSeams` default-throw members → **B7** (interface shape fixed
   here; `UNPORTED_RESOLVER_SEAM`, `details.seam` names which one).
2. `persistActive` (`ConfigManager.apply_session`) → **B8** via B7.
3. `MeCacheStore` on-disk twin (`me.py:413-607`) + the three MeCache
   test classes → **B8-N2** (`packages/node`).
4. `_format_no_project_error` wording → **B7** (`TODO(port)` at
   `workspace-members/lifecycle.ts`).
5. The `test_workspace_use.py` / `test_workspace_init.py` /
   `test_workspace.py` classes listed in §3 → **B7** / **B8**.

## §6 Gate checklist

- 15 members + 3 veneers + `[Symbol.asyncDispose]` live in
  `workspace.ts`; no `UNPORTED_MEMBER` throw remains anywhere in
  `packages/core/src`.
- `services/me.ts`, `workspace-members/lifecycle.ts`,
  `modelDumpExcludeNone` landed; resolver wiring installed at
  construction AND re-asserted across `use()`.
- `npm run typecheck` / `lint` / `fmt:check` / `test` / `smoke:browser`
  all green (`npm run check`): **181 files, 8,277 passed, 0 failed**.
- Vectors do NOT replay yet — binding is the separate fable BIND task
  (packet §11); vector green is that task's exit, charged back to W1 on
  failure.
