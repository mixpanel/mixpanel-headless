# B6 packets (design-lite) — the workspace facade bulk (the remaining 158 members)

**Status**: v1.0 · 2026-08-16 · P3-6 step-1 output for batch B6 (fable). Spec of
record: `context/phase3/design/phase3-playbook.md` v1.1 (P3-1 B6 row, P3-2 loop,
P3-3 tiering + 2026-08-15 revision, P3-5 flip rules, P3-6 B6 sharding, P3-7
referees) + Discrepancies #7–#12 + `user-ratifications.md`. Inbound deferrals:
`b5-packets.md` §8. Corpus pin `70c904dc` (verified in
`conformance-runner/corpus.config.json`); baseline at the B5 gate:
**2,876 PASS / 0 FAIL / 375 UNPORTED** (= 353 B6 workspace + 14 `region_probe.`
+ 7 `oauth_flow.` + 1 dagger holdback).

Every count below was MEASURED 2026-08-16 against the pinned corpus
(`find conformance-runner/corpus -name '*.jsonl' -exec cat {} + | jq -r
'select(.call.api|type=="string")|.call.api'` filtered to the 158 B6 member
names from `jq -r '.workspace_members[] | select(.batch=="B6") | .name'
context/typescript-port-api-map.json`). **The 158 member names sum to exactly
353 vectors**; the 1 carried dagger vector (§11.2) makes the gate delta **354**
(P3-1 † footnote).

---

## §0 Batch invariants (apply to W1–W8 alike)

1. **Tiering (P3-3 + 2026-08-15 revision)**: W-shard module tasks + their
   Layer-3 translations run on **opus**; the BIND task (§11), review pairs,
   arbiter, and the gate task (§12) run on **fable** (rig code / review never
   downgrades). Escalation: opus miss → retry once on fable with failure
   context; two misses abort the chain.
2. **R10.8 — compose, never re-implement.** Everything below the facade is
   ALREADY LIVE: B0 client internals (`packages/core/src/client/*`), the B4
   wire client incl. every entity method group
   (`packages/core/src/services/entities/*.ts`, composed onto the client at
   `client.ts:1077+`), `response-validation.ts` (B4-C1, R10.8 ownership note in
   its header), the B5 services and the `workspace.ts` skeleton. A B6 facade
   member is a THIN delegation: options-bag mapping (R3.3/R3.8) → the
   like-named client method → entity-model construction via
   `validateResponseModel(s)`. Grep-auditable at review: no request assembly,
   no header merging, no URL building, no status branching inside
   `workspace.ts` / the member modules.
3. **Behavior arbiter is Python at current support-branch HEAD.** The api-map
   `lineno` fields have drifted ~+300 lines (B5 Caution #15); every line cite
   in this packet is re-measured at HEAD 2026-08-16 (`workspace.py` = 11,292
   lines). Re-measure after any upstream merge (P3-7 trigger 4).
4. **Codes, not messages (R5)**; R3.9 optionality; R4.8 `Object.hasOwn`;
   watchlist #13 `isinstance(x, dict)` discrimination (reuse
   `isPlainRecord` from `services/entities/shared.ts` — never re-derive);
   R11.7 (`pythonStrip`/`pythonInt` — bare `trim`/`parseInt`/`Number()`
   forbidden); **R2.13 — NO `new URL()`** anywhere in ported code; R1.3 JSDoc
   on everything.
5. **Discrepancy semantics ratified and binding**: #8 (contract scope = the
   declared annotation — out-of-annotation CPython raises are unspecified),
   #9/#10 (integer-like unknown-key emission order — W3 is the named
   re-examination site for #10, see §5), #12 (integral-float spelling
   narrowing in output text).
6. **Vectors replay through the REAL facade** (P3-5 rule 3). The B5
   `wire-workspace.ts` pattern is the template: `workspaceFromSession(context)`
   (`conformance-runner/src/wire-workspace.ts:159`) memoized under the single
   well-known state key, over the shared `clientFromSession` client
   (`wire-client.ts:243-283`), so `call.setup[]` entries (22
   `api_client.set_workspace_id` setups ride on B6-measured vectors — measured
   2026-08-16) mutate the same instance.
7. **No mutation testing** `[SA1]`. R10.13 incremental-work protocol on every
   agent (skeleton first, small frequent edits, notes file
   `context/phase3/notes/B6-<shard>-notes.md`). analytics repo READ-ONLY.
   Python via `uv`; the literal p-y-t-e-s-t string and bare `python` are
   hook-blocked.
8. **Done per shard** = shard done-criteria (§3–§10) + `npm run check` green +
   `just check` green when the Python repo was touched + local commits on the
   correct branches (TS `main`, Python `ts-port/phase2-contract-support`;
   NEVER push).

---

## §1 Measured vector budget (sums to exactly 353; +1 dagger at the gate)

| Shard | Section groups (api-map `section` values) | Members | Vectors | Zero-vector members |
|---|---|---|---|---|
| W1 | LIFECYCLE & CONSTRUCTION (6) + WORKSPACE MANAGEMENT (2) + /ME & PROJECT DISCOVERY (3) + business context (4; api-map section header reads "Markdown documentation that grounds AI assistants in the") | 15 | 15 | 9 (`account`, `project`, `workspace`, `session`, `use`, `close`, `me`, `projects`, `workspaces`) |
| W2 | DASHBOARD CRUD (6) + DASHBOARD ADVANCED OPERATIONS (16) | 22 | 38 | 10 (`favorite_dashboard`, `unfavorite_dashboard`, `pin_dashboard`, `unpin_dashboard`, `list_blueprint_templates`, `create_blueprint`, `get_blueprint_config`, `get_bookmark_dashboard_ids`, `get_dashboard_erf`, `update_text_card`) |
| W3 | BOOKMARK/REPORT CRUD (9) + COHORT CRUD (7) | 16 | 89 | 0 |
| W4 | FEATURE FLAG CRUD (5) + LIFECYCLE (3) + OPERATIONS (3) + EXPERIMENT CRUD (5) + LIFECYCLE (3) + MANAGEMENT (4) | 23 | 40 | 0 |
| W5 | Annotations (7) + Webhook CRUD (5) + Alert CRUD (11) | 23 | 43 | 0 |
| W6 | Data Governance — Data Definitions / Lexicon (11) + Tracking & History (4) | 15 | 33 | 0 |
| W7 | Data Governance — Drop Filters (5) + Custom Properties (6) + Lookup Tables (9) + Custom Events (4) | 24 | 44 | 1 (`upload_lookup_table`) |
| W8 | Schema Registry CRUD (6) + Schema Enforcement (5) + Data Auditing (2) + Data Volume Anomalies (3) + Event Deletion Requests (4) | 20 | 51 | 0 |
| **Σ** | | **158** | **353** | **20** |

Shard naming: this packet uses **W1–W8**; the playbook P3-6 table names the
same eight groups W1–W5, **W6a, W6b, W7** — the alias is W6≡W6a, W7≡W6b,
W8≡playbook-W7. Counts match the playbook row exactly
(15/22/16/23/23/15/24/20, Σ=158).

**Zero-vector members (20)**: per the B5 Caution-#13 precedent
(`discovery-facade.test.ts` header pattern), zero-vector members get ADDITIVE
delegation-contract tests in the owning shard's Layer-3 suite — which service /
client method is called, with which arguments, plus any non-forwarding facade
logic — clearly headed as additive, never substituting for a translated Python
assertion. Their Layer-3 suites are the ONLY behavior lock; R10.2 diligence on
those files is the review pair's top item (risk-register #3).

**The dagger (P3-1 †)**: vector
`auth/api_client.resolve_workspace_id/test_workspace_resolution-testfacaderesolverwiring-test_resolves_from_me_cache_without_public_call`
(measured `api_client.resolve_workspace_id`, setup `workspace.me`, capability
`auth`) stays UNPORTED until the B6 gate and first PASSes there — gate delta
**354**. Verified in the pinned corpus 2026-08-16: session
`{account_name: facade, project_id: "4025120", type: service_account}`, ONE
recorded interaction (`GET https://mixpanel.com/api/app/me`, Basic `dTpz`),
expected result `2` — i.e. the measured call must resolve from the me-cache
WITHOUT a public-workspaces call. §11.2 owns the closure.

---

## §2 Shard map, sequencing, and the workspace.ts merge plan

**Sequencing**: **W1 FIRST** (lifecycle/use/close + the B5 §8 outbound
deferrals — everything else asserts against a facade whose lifecycle
members exist, and W1 lands the shared `modelDumpExcludeNone` flattening
helper §3.4 that W2–W8 consume). Then **W2, W4, W5, W6, W7, W8 in parallel**.
**W3 LAST** (it owns the two cross-entity suites —
`test_workspace_crud_edge.py` parametrizes members from every entity shard and
`test_delegation_equivalence_pbt.py` is tier-independent PBT — so its Layer-3
step needs W2/W4–W8's members on disk). Binding (§11) after all eight shards;
gate (§12) last.

**workspace.ts merge plan** (risk-register #6): the B5 skeleton ends with the
marker `// === B6 members land below in W1–W7 sections (append-only) ===`
(`packages/core/src/workspace.ts:2509`; the marker's "W1–W7" spelling predates
this packet's W1–W8 naming — same eight groups). Each shard:

- owns ONE marked append-only section inside the class, inserted in shard
  order (`// === B6-W<N> <domain> members (W<N> owns; append-only) ===`);
  method bodies there are ONE-LINE delegations;
- puts its options interfaces + any member-module logic in a per-domain module
  `packages/core/src/workspace-members/<domain>.ts` (new directory; W1 creates
  it) so parallel shards touch `workspace.ts` only in tiny disjoint blocks;
- never edits another shard's section; the gate task is the single integrator
  if the orchestrator's parallel dispatch produces a merge point.

Per-domain member modules (TS homes, all under `packages/core/src/`):

| Shard | workspace.ts section | member module | leans on (already live) |
|---|---|---|---|
| W1 | B6-W1 lifecycle | `workspace-members/lifecycle.ts` + `services/me.ts` (NEW — MeService, §3.3) | `client.use/close` (B4-C1), `client/me.ts` models + `selectWorkspaceId` (B4-C1), `setWorkspaceResolver` seam (`client.ts:1114`), `services/entities/business-context.ts`, `services/queries/streaming.ts` |
| W2 | B6-W2 dashboards | `workspace-members/dashboards.ts` | `services/entities/dashboards.ts` (B4-C3), `client/response-validation.ts`, `types/entities/dashboards.ts` (Phase 2) |
| W3 | B6-W3 bookmarks+cohorts | `workspace-members/bookmarks-cohorts.ts` | `services/entities/bookmarks.ts` + `cohorts.ts` (B4-C3), `bookmarks/*` schema validators (B2/B3), `types/entities/{bookmarks,cohorts}.ts` |
| W4 | B6-W4 flags+experiments | `workspace-members/flags-experiments.ts` | `services/entities/{flags,experiments}.ts` (B4-C4), `types/entities/{feature-flags,experiments}.ts` |
| W5 | B6-W5 annotations+webhooks+alerts | `workspace-members/annotations-webhooks-alerts.ts` | `services/entities/{annotations,webhooks,alerts}.ts` (B4-C4), `types/entities/{annotations,webhooks,alerts}.ts` |
| W6 | B6-W6 lexicon+tracking | `workspace-members/lexicon-tracking.ts` | `services/entities/lexicon.ts` (B4-C5), `types/entities/{lexicon,data-governance}.ts` |
| W7 | B6-W7 governance-data | `workspace-members/governance-data.ts` | `services/entities/{drop-filters,custom-properties,lookup-tables,custom-events}.ts` (B4-C5), `types/entities/data-governance.ts` |
| W8 | B6-W8 schemas+audit | `workspace-members/schemas-audit.ts` | `services/entities/{schemas,schema-enforcement,audit,anomalies,deletion-requests}.ts` (B4-C5), `types/entities/schemas.ts` |

Each shard also re-exports its options interfaces from `workspace.ts` (the
B5 export pattern — see the `Workspace*Options` exports consumed by
`wire-workspace.ts:44-75`).

**Entity-client factory note (R2.9)**: the playbook B6 row's
"`create<Entity>Client({transport, getScope})` factories" landed at B4 as the
`create<Entity>Methods(core)` groups composed onto the client
(`client.ts:1077+`) — the B4-C3/C4/C5 shards built them ahead of schedule.
W-shards therefore DELEGATE to `this.client.<method>`; they do not build new
factories. (Recorded so the review pair doesn't flag a missing deliverable.)

---
## §3 Packet W1 — lifecycle & construction + workspace management + /me trio + business context + the B5 §8 deferrals (opus; runs FIRST)

### Members (15) + api-map rows (PASTED — this IS the contract)

**LIFECYCLE & CONSTRUCTION** (6 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `account` | :531 | **0** | `get account(): _AccountUnion` | — | — | `_AccountUnion` |
| `project` | :536 | **0** | `get project(): _Project` | — | — | `_Project` |
| `workspace` | :541 | **0** | `get workspace(): _WorkspaceRef \| None` | — | — | `_WorkspaceRef \| None` |
| `session` | :546 | **0** | `get session(): _Session` | — | — | `_Session` |
| `use` | :552 | **0** | `async use(account, project, workspace, …): Promise<Workspace>` | — | `account`, `project`, `workspace`, `target`, `persist` | `Workspace` |
| `close` | :744 | **0** | `async close(): Promise<void>` | — | — | `None` |

**WORKSPACE MANAGEMENT** (2 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_workspaces` | :801 | 2 | `async list_workspaces(): Promise<list[PublicWorkspace]>` | — | — | `list[PublicWorkspace]` |
| `resolve_workspace_id` | :827 | 1 | `async resolve_workspace_id(): Promise<number>` | — | — | `int` |

**/ME & PROJECT DISCOVERY** (3 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `me` | :886 | **0** | `async me(force_refresh): Promise<Any>` | — | `force_refresh` | `Any` |
| `projects` | :913 | **0** | `async projects(refresh): Promise<list[_Project]>` | — | `refresh` | `list[_Project]` |
| `workspaces` | :958 | **0** | `async workspaces(project_id, refresh): Promise<list[_WorkspaceRef]>` | — | `project_id`, `refresh` | `list[_WorkspaceRef]` |

**Markdown documentation that grounds AI assistants in the** (4 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `get_business_context` | :10405 | 4 | `async get_business_context(level, organization_id): Promise<BusinessContext>` | — | `level`, `organization_id` | `BusinessContext` |
| `set_business_context` | :10481 | 4 | `async set_business_context(content, level, organization_id): Promise<BusinessContext>` | `content` | `level`, `organization_id` | `BusinessContext` |
| `clear_business_context` | :10568 | 1 | `async clear_business_context(level, organization_id): Promise<BusinessContext>` | — | `level`, `organization_id` | `BusinessContext` |
| `get_business_context_chain` | :10612 | 3 | `async get_business_context_chain(): Promise<BusinessContextChain>` | — | — | `BusinessContextChain` |

### Scope / Python sources (re-read all ranges at HEAD)

- `workspace.py:528-548` — the four read-only properties (`account` :531,
  `project` :536, `workspace` :541, `session` :546). TS: `get` accessors over
  `this.session` (pure, no I/O — R3.1 lets them stay sync accessors).
- `workspace.py:550-753` — `use()` :552-694, `_persist_active` :696-722,
  `__enter__`/`__exit__` :723-742, `close()` :744-753.
- `workspace.py:797-861` — `list_workspaces` :801 (pure delegation to
  `client.list_workspaces()` — the client already returns `PublicWorkspace`
  models via response validation), `resolve_workspace_id` :827 (pure
  delegation to `client.resolve_workspace_id()`).
- `workspace.py:862-1034` — `_me_svc` lazy property :866-885, `me()` :886,
  `projects()` :913, `workspaces()` :958.
- `workspace.py:10254-10674` — business context: `get_business_context`
  :10405, `set_business_context` :10481, `clear_business_context` :10568,
  `get_business_context_chain` :10612. All four delegate to the like-named
  client methods (`services/entities/business-context.ts`, B4-C5); the facade
  adds the level axis (kwonly `level: "organization" | "project"` — default
  `"project"` — plus `organization_id`, `workspace.py:10405-10410`) and
  result-model construction.
- `_internal/me.py:609-915` — **MeService ports HERE** (§3.3).
- **B5 §8 deferred veneers**: `stream_events` `workspace.py:1400-1467`,
  `stream_profiles` :1469-1578, `api` escape-hatch property :4464-4501.

### W1 design decisions (arbiter-visible, S3-D1 precedent)

1. **W1-D1 — `use()` resolver seams.** Python `use()` consumes B7/B8 surfaces
   in two of its three branches: `target=` routes through `_resolve_session` +
   `_load_bridge` + `ConfigManager` (`workspace.py:618-630`); `account=` loads
   via `cm.get_account` + `_resolve_project_axis` + `_env_workspace_id`
   (:631-668); `persist=True` calls `ConfigManager().apply_session`
   (:696-722). The playbook B7 row says "`Workspace.use(...)` (B6, already
   built) consumes `resolve_session`" — i.e. B6 builds the member, B7/B8
   supply the resolution. **Decision**: W1 ports the WS1 guard + the pure
   project/workspace-axis branch (:669-677) + the axis-swap core
   (`client.use(...)` delegation, session refresh, cache clears) in full, and
   defines an injectable `ResolverSeams` interface on `WorkspaceOptions`
   (`resolveSession`, `getAccount`, `resolveProjectAxis`, `envWorkspaceId`,
   `persistActive`) whose DEFAULT implementations throw
   `MixpanelHeadlessError` code `UNPORTED_RESOLVER_SEAM` with a
   `TODO(port): B7` owner marker. B7 replaces the defaults; B8 supplies
   config/bridge I/O. The seam interface shape is W1's deliverable — B7's
   packet consumes it by name.
2. **W1-D2 — `close()` vs the B5 `readonly client`.** Python `close()`
   (:744-753) nulls `_api_client` and `_get_api_client` (:757+) lazily
   RECREATES one on next use; the B5 TS skeleton holds `readonly client`.
   Decide at implementation (arbiter-visible): either drop `readonly` and
   port the null-and-recreate cycle, or close the pool in place and let the
   next call reuse the closed client's injected fetch (Python-observable
   difference: Python's recreated client re-reads nothing — construction is
   pure — so closing in place + allowing further calls diverges only if the
   transport enforces closed-ness). The Layer-3 lock is
   `test_workspace.py::TestContextManager` (:712) — idempotent close, usable
   in `with` — plus R6.2's `[Symbol.asyncDispose]` → `close()` chain already
   stubbed at `workspace.ts:733-737`. Whichever way, `close()` must be
   idempotent and `use()` after `close()` must behave as Python does (verify
   against the Python source before choosing).
3. **W1-D3 — stream veneer decision (B5 §8 outbound deferral, CLOSED here).**
   `stream_events`/`stream_profiles` land as R6.6 **item-level `yield*`
   veneers** over the B4 client streaming methods
   (`services/queries/streaming.ts`), `AsyncIterable` returned directly
   (R3.2, no Promise wrapper). They remain PROJECT-scoped by design even when
   a workspace is pinned (`use()` docstring, `workspace.py:566-573` — "Raw
   export streaming remains project-scoped"); the veneer must NOT thread
   workspace scoping. `get api()` returns `this.client` (escape hatch,
   `workspace.py:4464-4501`). All three are batch-B4 api-map members with
   ZERO corpus vectors (measured); their locks are the translated
   `test_workspace_streaming.py` suites + additive delegation tests.
4. **W1-D4 — shared entity-params flattening helper.** Python facade members
   serialize Pydantic params via `params.model_dump(exclude_none=True)`
   (e.g. `create_dashboard` `workspace.py:4564`, `create_cohort` :5643).
   The Phase-2 `EntityModel` base has `toJSON()`/`toVectorPayload()`
   (`types/entities/model-base.ts:495,501`) but NO exclude-none dump. W1 adds
   **one** `modelDumpExcludeNone()` to `model-base.ts` (R10.8 — single
   implementation; pydantic v2 `exclude_none=True` recurses into nested
   models — match that, and note `toJSON()` is NOT it: `toJSON` keeps `None`
   fields as `null`). W2–W8 consume it by name; a shard re-deriving the dump
   is a review finding.

### MeService (§3.3): the me.py split, completed

`_internal/me.py` is split three ways (playbook Discrepancy #5 + B4-C1):
models + `WorkspaceView` + `selectWorkspaceId` are DONE in
`packages/core/src/client/me.ts` (its header: "MeService halves are B8-N2 and
MUST NOT be ported or stubbed **here**" — the prohibition is scoped to that
B4 module file); the ON-DISK `MeCache` (`me.py:413-607`) is B8-N2. W1 ports
**`MeService` (`me.py:609-915`)** to `packages/core/src/services/me.ts` with a
`MeCacheStore` interface (`get`/`put`/`invalidate` — mirror `MeCache`'s
surface at :470/:546/:597) injected via the constructor; W1 ships an
IN-MEMORY default store; B8-N2 implements the on-disk twin in
`packages/node`. `me()`/`projects()`/`workspaces()` delegate to the lazily
constructed service exactly as `_me_svc` does (:866-885: constructed with the
client, the cache, the session's region and account type). **Wiring that
closes the dagger**: Workspace construction (and every `use()` swap) installs
`client.setWorkspaceResolver((pid) => meSvc.resolveWorkspace(pid))`
(`workspace.py:787`, seam already live at `client.ts:1114`; Python client
counterpart `api_client.py:352`) — that is HOW the B4-C1
`resolveWorkspaceId` reads "the cached /me view" without a public call, and
it is what the dagger vector measures. The B5 skeleton constructor does not
install it yet; W1 adds it.

### R6.2 — the connection-reuse invariant (CRITICAL)

`ws.use(...)` delegates the swap to `client.use(...)`
(`workspace.py:672-677`), which rebuilds auth IN PLACE on the same client;
the facade then refreshes `self._session = client.session` and clears every
lazy service (`:679-693`: `_discovery`, `_live_query`, `_me_service`,
`_replays_svc`, plus `_account_name` / `_initial_workspace_id` refresh). TS
locks: (i) `ws.client` is the SAME object reference before and after `use()`
(the Python identity locks are
`test_workspace_use.py::TestHTTPTransportPreservation` (:132) and
`tests/integration/test_cross_project_iteration.py` `id()` assertions);
(ii) the lazy `#discovery`/`#liveQuery`/`#replays` fields AND the new
`#meService` reset to `null` on every switch — locked by
`TestUseUpdatesSessionAndClearsCaches` (:255) and by the B5 §8 inbound
deferral `TestDiscoveryCacheAcrossUse`
(`tests/unit/test_query_workspace_scoping.py`, deferred B4-C1 → B5 → HERE:
translate into `test/workspace/facade-scoping.test.ts`'s file or a sibling,
header-cited). The WS1 guard (`WS1_TARGET_MUTUALLY_EXCLUSIVE`,
`workspace.py:605-611`; the CONSTRUCTOR carries its own twin at :455-465 —
that one is B7's, behind the resolver kwargs) fires BEFORE any resolution
work.

### Layer-3 translation scope (class-split, phase2-audit A2 header-cite style)

| Python source | W1 takes | Defers (owner) |
|---|---|---|
| `tests/unit/test_workspace.py` (1,026 lines) | `TestLiveQueries` (:118), `TestDiscovery` (:439), `TestContextManager` (:712), `TestLimitValidation` (:754), `TestWorkspacesMethod` (:808), `TestProjectsMethod` (:861), `TestCodedWorkspaceGuardCodes` (:919) → `test/workspace/workspace-facade.test.ts` | `TestCredentialResolution` (:96) → B7 (resolver) |
| `tests/unit/test_workspace_use.py` (417 lines) | `TestUseWorkspace` (:56), `TestUseProject` (:72), `TestHTTPTransportPreservation` (:132), `TestTargetMutualExclusion` (:169), `TestUseUpdatesSessionAndClearsCaches` (:255) → `test/workspace/workspace-use.test.ts` | `TestUseAccount` (:89), `TestPersist` (:190), `TestUseAccountEnvVarPriority` (:221), `TestUseTargetEnvOverride` (:346), `TestUseAccountWorkspaceEnvValidation` (:384) → B7 (all exercise config/bridge/env resolution through the W1-D1 seams) |
| `tests/unit/test_workspace_init.py` (234 lines) | `TestSessionBypass` (:115), `TestReadOnlyProperties` (:151) → `test/workspace/workspace-init.test.ts` | `TestActiveResolution` (:66), `TestExplicitOverrides` (:76), `TestTarget` (:96) → B7; `TestBridgeTokenMaterialization` (:167) → B8 |
| `tests/unit/test_workspace_streaming.py` (744 lines) | WHOLE file (`TestStreamEvents` :106, `TestStreamProfiles` :369, `TestNormalizedEventFormat` :622, `TestRawEventFormat` :659, `TestNormalizedProfileFormat` :689, `TestRawProfileFormat` :720) → `test/workspace/workspace-streaming.test.ts` | — |
| `tests/unit/test_workspace_business_context.py` (583 lines) | WHOLE file (6 classes, :146-:483) → `test/workspace/business-context.test.ts` | — |
| `TestDiscoveryCacheAcrossUse` (from `tests/unit/test_query_workspace_scoping.py`; B5 §8 inbound) | → W1 (see R6.2 block above) | — |
| `tests/unit/test_042_edge_cases.py` (681 lines) | **NONE — playbook misassignment** (Discrepancy log §14.1): the file has zero `Workspace(` call sites (verified 2026-08-16); its 9 classes are resolver/auth-types/bridge/config/CLI surfaces | `TestAccountNameBoundaries` (:52), `TestOAuthTokenValidatorUnderCopy` (:105), `TestSessionReplaceSentinel` (:168), `TestResolverEdgeCases` (:325) → B7; `TestTokenResolverMalformed` (:240), `TestBridgeEdgeCases` (:394), `TestConfigManagerEdgeCases` (:459) → B8; `TestCliExitCodes` (:550), `TestSecretLeakage` (:615) → B7 packet author decides (CLI is outside the port's library scope — document, don't drop silently) |

### R10.10 consumers

End users (playbook B6 row): the Python docstring `Example:` blocks at the
cited source ranges are the ergonomics reference — the shard agent re-reads
them before shaping options bags. Representative (the `use()` contract,
`workspace.py:561-597`): `ws.use(workspace=12345)` pins App-API scoping;
account swap clears the pin; `for project in ws.projects():
ws.use(project=project.id)` is the documented cross-project iteration
pattern. Internal consumers: `wire-workspace.ts` (facade twin construction —
§11), every W2–W8 member (the `modelDumpExcludeNone` helper, the merged
constructor wiring), B7 (the `ResolverSeams` interface).

### R10.9 harness spec — `throwaway/b6-w1/`

Facade harness (wire members have no oracle-call surface — edge set through
`VectorFetch` with hand-built interactions): (i) delegation-equivalence
probes — for `list_workspaces`, `resolve_workspace_id`, `me`, and the four
business-context members, assert facade result === direct client/service
result over the same canned interaction set; (ii) wire status branches for
2-3 representative members (`me`: 200 + 401 + 403; `set_business_context`:
200 + 400 + 429-exhausted; `list_workspaces`: 200-empty + 500); (iii) the
mandatory edge set verbatim (integral float `18.0`, `1.5`, `True`, `None`,
empty list, empty string, `"𝒳"`) pushed through `use()` kwargs and
business-context params where the annotation admits them (#8 boundary);
(iv) EVERY W1-local error branch: `WS1_TARGET_MUTUALLY_EXCLUSIVE`,
`UNPORTED_RESOLVER_SEAM` (all five seam defaults), the me()-unavailable
ConfigError path, close-idempotency double-call. RUN record (counts, seeds)
→ `context/phase3/notes/B6-W1-notes.md`.

### Done-criteria (W1)

All 15 members + the 3 veneer members live in `workspace.ts` (stubs at
:699-737 replaced; `UNPORTED_MEMBER` throws gone); `services/me.ts` +
`workspace-members/lifecycle.ts` + `modelDumpExcludeNone` landed; the
`setWorkspaceResolver` wiring installed at construction AND re-installed
across `use()`; translated Layer-3 green; `tsc --strict` clean;
`npm run check` green; harness RUN record written; notes file committed.
Vectors CANNOT replay yet (binding is §11) — vector green is the BIND task's
exit, charged back to W1 on failure.

---

## §4 Packet W2 — dashboards: CRUD + advanced operations (opus; parallel after W1)

### Members (22) + api-map rows (PASTED)

**DASHBOARD CRUD (Phase 024)** (6 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_dashboards` | :4506 | 6 | `async list_dashboards(ids): Promise<list[Dashboard]>` | — | `ids` | `list[Dashboard]` |
| `create_dashboard` | :4538 | 5 | `async create_dashboard(params): Promise<Dashboard>` | `params` | — | `Dashboard` |
| `get_dashboard` | :4571 | 10 | `async get_dashboard(dashboard_id): Promise<Dashboard>` | `dashboard_id` | — | `Dashboard` |
| `update_dashboard` | :4602 | 4 | `async update_dashboard(dashboard_id, params): Promise<Dashboard>` | `dashboard_id`, `params` | — | `Dashboard` |
| `delete_dashboard` | :4640 | 2 | `async delete_dashboard(dashboard_id): Promise<void>` | `dashboard_id` | — | `None` |
| `bulk_delete_dashboards` | :4661 | 3 | `async bulk_delete_dashboards(ids): Promise<void>` | `ids` | — | `None` |

**DASHBOARD ADVANCED OPERATIONS (Phase 024)** (16 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `favorite_dashboard` | :4686 | **0** | `async favorite_dashboard(dashboard_id): Promise<void>` | `dashboard_id` | — | `None` |
| `unfavorite_dashboard` | :4707 | **0** | `async unfavorite_dashboard(dashboard_id): Promise<void>` | `dashboard_id` | — | `None` |
| `pin_dashboard` | :4728 | **0** | `async pin_dashboard(dashboard_id): Promise<void>` | `dashboard_id` | — | `None` |
| `unpin_dashboard` | :4749 | **0** | `async unpin_dashboard(dashboard_id): Promise<void>` | `dashboard_id` | — | `None` |
| `remove_report_from_dashboard` | :4770 | 1 | `async remove_report_from_dashboard(dashboard_id, bookmark_id): Promise<Dashboard>` | `dashboard_id`, `bookmark_id` | — | `Dashboard` |
| `add_report_to_dashboard` | :4802 | 3 | `async add_report_to_dashboard(dashboard_id, bookmark_id): Promise<Dashboard>` | `dashboard_id`, `bookmark_id` | — | `Dashboard` |
| `list_blueprint_templates` | :4841 | **0** | `async list_blueprint_templates(include_reports): Promise<list[BlueprintTemplate]>` | — | `include_reports` | `list[BlueprintTemplate]` |
| `create_blueprint` | :4871 | **0** | `async create_blueprint(template_type): Promise<Dashboard>` | `template_type` | — | `Dashboard` |
| `get_blueprint_config` | :4902 | **0** | `async get_blueprint_config(dashboard_id): Promise<BlueprintConfig>` | `dashboard_id` | — | `BlueprintConfig` |
| `update_blueprint_cohorts` | :4935 | 1 | `async update_blueprint_cohorts(cohorts): Promise<void>` | `cohorts` | — | `None` |
| `finalize_blueprint` | :4956 | 1 | `async finalize_blueprint(params): Promise<Dashboard>` | `params` | — | `Dashboard` |
| `create_rca_dashboard` | :4993 | 1 | `async create_rca_dashboard(params): Promise<Dashboard>` | `params` | — | `Dashboard` |
| `get_bookmark_dashboard_ids` | :5030 | **0** | `async get_bookmark_dashboard_ids(bookmark_id): Promise<list[int]>` | `bookmark_id` | — | `list[int]` |
| `get_dashboard_erf` | :5054 | **0** | `async get_dashboard_erf(dashboard_id): Promise<Record<string, unknown>>` | `dashboard_id` | — | `dict[str, Any]` |
| `update_report_link` | :5078 | 1 | `async update_report_link(dashboard_id, report_link_id, params): Promise<void>` | `dashboard_id`, `report_link_id`, `params` | — | `None` |
| `update_text_card` | :5112 | **0** | `async update_text_card(dashboard_id, text_card_id, params): Promise<void>` | `dashboard_id`, `text_card_id`, `params` | — | `None` |

### Scope / Python sources

`workspace.py:4504-5145` (HEAD; section markers "DASHBOARD CRUD (Phase 024)"
:4502-4504 through the BOOKMARK header :5146). Every member delegates to the
like-named client method (`services/entities/dashboards.ts`, B4-C3, ported
from `api_client.py:3650-4426`) and shapes results via
`validateResponseModel(s)(Dashboard | ...)` — `list_dashboards` :4506,
`create_dashboard` :4538 (empty-response guard → `MixpanelHeadlessError`
default code `UNKNOWN_ERROR` — port the guard, not the message), through
`update_text_card` :5112. `create_rca_dashboard` and the blueprint trio
carry multi-step Python bodies — re-read :4855-5010 and port branch-for-branch.

### TS homes / Layer-3 / consumers / harness / done

- Home: `workspace-members/dashboards.ts` + the B6-W2 workspace.ts section.
- Layer-3 (class-split of `tests/unit/test_workspace_crud.py`, 1,861 lines):
  `TestWorkspaceDashboardCRUD` (:189), `TestWorkspaceBlueprintCohorts`
  (:1763), `TestRemoveReportFromDashboard` (:1785),
  `TestAddReportToDashboard` (:1812) → `test/workspace/crud-dashboards.test.ts`.
  The 10 zero-vector members (§1) get additive delegation tests per the
  Caution-#13 pattern in the same file.
- R10.10: end users (docstring examples at the cited ranges, e.g.
  `create_dashboard` `workspace.py:4556-4562`); `wire-workspace` bindings §11.
- R10.9 `throwaway/b6-w2/`: delegation-equivalence probes + status branches
  for `get_dashboard` (200/404/empty-body) and `add_report_to_dashboard`
  (200/400/422-via-app_request); edge set through `ids=`/params fields;
  every facade-local error branch (empty-response guards, response-validation
  RESPONSE_VALIDATION_ERROR via a malformed 200 body).
- Done: 22 members live; translated tests green; `npm run check`; notes
  `B6-W2-notes.md`; local commit.

---

## §5 Packet W3 — bookmarks/reports + cohorts + the cross-entity suites (opus; runs LAST of W2–W8)

### Members (16) + api-map rows (PASTED)

**BOOKMARK/REPORT CRUD (Phase 024)** (9 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_bookmarks_v2` | :5150 | 7 | `async list_bookmarks_v2(bookmark_type, ids): Promise<list[Bookmark]>` | — | `bookmark_type`, `ids` | `list[Bookmark]` |
| `create_bookmark` | :5247 | 8 | `async create_bookmark(params): Promise<Bookmark>` | `params` | — | `Bookmark` |
| `get_bookmark` | :5326 | 23 | `async get_bookmark(bookmark_id): Promise<Bookmark>` | `bookmark_id` | — | `Bookmark` |
| `update_bookmark` | :5357 | 5 | `async update_bookmark(bookmark_id, params): Promise<Bookmark>` | `bookmark_id`, `params` | — | `Bookmark` |
| `delete_bookmark` | :5416 | 2 | `async delete_bookmark(bookmark_id): Promise<void>` | `bookmark_id` | — | `None` |
| `bulk_delete_bookmarks` | :5437 | 3 | `async bulk_delete_bookmarks(ids): Promise<void>` | `ids` | — | `None` |
| `bulk_update_bookmarks` | :5458 | 4 | `async bulk_update_bookmarks(entries): Promise<void>` | `entries` | — | `None` |
| `bookmark_linked_dashboard_ids` | :5481 | 3 | `async bookmark_linked_dashboard_ids(bookmark_id): Promise<list[int]>` | `bookmark_id` | — | `list[int]` |
| `get_bookmark_history` | :5505 | 3 | `async get_bookmark_history(bookmark_id, cursor, page_size): Promise<BookmarkHistoryResponse>` | `bookmark_id` | `cursor`, `page_size` | `BookmarkHistoryResponse` |

**COHORT CRUD (Phase 024)** (7 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_cohorts_full` | :5548 | 6 | `async list_cohorts_full(data_group_id, ids): Promise<list[Cohort]>` | — | `data_group_id`, `ids` | `list[Cohort]` |
| `get_cohort` | :5586 | 5 | `async get_cohort(cohort_id): Promise<Cohort>` | `cohort_id` | — | `Cohort` |
| `create_cohort` | :5617 | 6 | `async create_cohort(params): Promise<Cohort>` | `params` | — | `Cohort` |
| `update_cohort` | :5650 | 5 | `async update_cohort(cohort_id, params): Promise<Cohort>` | `cohort_id`, `params` | — | `Cohort` |
| `delete_cohort` | :5684 | 2 | `async delete_cohort(cohort_id): Promise<void>` | `cohort_id` | — | `None` |
| `bulk_delete_cohorts` | :5705 | 3 | `async bulk_delete_cohorts(ids): Promise<void>` | `ids` | — | `None` |
| `bulk_update_cohorts` | :5726 | 4 | `async bulk_update_cohorts(entries): Promise<void>` | `entries` | — | `None` |

### Scope / Python sources

`workspace.py:5146-5748` (HEAD): bookmark CRUD :5150-5543 — including the
PRIVATE `_validate_bookmark_params_schema` :5186-5245 (consumes the B3
`bookmark_schema` surface; called from `create_bookmark` :5296 and
`update_bookmark` :5396) — then cohort CRUD :5546-5748. `create_cohort`
:5617 (dump at :5643) / `update_cohort` :5650 (:5677) flatten params via
`model_dump(exclude_none=True)` → the W1-D4 helper; `bulk_update_bookmarks`
:5479 and `bulk_update_cohorts` :5747 flatten per-entry lists.

**Discrepancy #10 re-examination duty (named site)**: `#10`'s ruling defers
re-examination "at the B6-W3 review" — the shard notes MUST record whether any
W3 surface exposes `extra_forbidden` warning-list ordering across integer-like
unknown keys to a consumer who could depend on it; the review pair verifies
the note. Integer-like unknown keys stay excluded from any fuzz domain W3
adds.

### TS homes / Layer-3 / consumers / harness / done

- Home: `workspace-members/bookmarks-cohorts.ts` + the B6-W3 section.
- Layer-3: `tests/unit/test_workspace_bookmarks.py` (WHOLE) →
  `test/workspace/workspace-bookmarks.test.ts`; from
  `tests/unit/test_workspace_crud.py`: `TestWorkspaceBookmarkCRUD` (:530) +
  `TestWorkspaceCohortCRUD` (:1319) →
  `test/workspace/crud-bookmarks-cohorts.test.ts`; **the two cross-entity
  suites** (why W3 runs last): `tests/unit/test_workspace_crud_edge.py`
  (WHOLE — `TestRequestBodySerialization` :92, `TestEmptyResponseHandling`
  :247, `TestWorkspaceMethodDelegation` :298,
  `TestCodedResponseValidationCodes` :416; parametrized over members owned by
  every entity shard) → `test/workspace/crud-edge.test.ts`; and
  `tests/unit/test_delegation_equivalence_pbt.py` (validator-level
  Hypothesis suites — fast-check with the same strategy shapes) →
  `test/workspace/delegation-equivalence.pbt.test.ts`.
- R10.10: end users; referee feed (§12.4 — bookmark-emitting surfaces);
  `wire-workspace` bindings §11.
- R10.9 `throwaway/b6-w3/`: delegation-equivalence probes + status branches
  for `get_bookmark` (200/404/500) and `create_cohort`
  (200/400/empty-body); edge set through bookmark params dicts
  (annotation-bounded per #8; NO integer-like unknown keys per #9/#10);
  every W3-local error branch incl. the `_validate_bookmark_params_schema`
  warning path and both empty-response guards.
- Done: 16 members + the private validator live; all four Layer-3 files
  green; `npm run check`; notes `B6-W3-notes.md`; local commit.

---

## §6 Packet W4 — feature flags + experiments (opus; parallel after W1)

### Members (23) + api-map rows (PASTED)

**FEATURE FLAG CRUD (Phase 025)** (5 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_feature_flags` | :5753 | 5 | `async list_feature_flags(include_archived): Promise<list[FeatureFlag]>` | — | `include_archived` | `list[FeatureFlag]` |
| `create_feature_flag` | :5784 | 2 | `async create_feature_flag(params): Promise<FeatureFlag>` | `params` | — | `FeatureFlag` |
| `get_feature_flag` | :5817 | 3 | `async get_feature_flag(flag_id): Promise<FeatureFlag>` | `flag_id` | — | `FeatureFlag` |
| `update_feature_flag` | :5848 | 1 | `async update_feature_flag(flag_id, params): Promise<FeatureFlag>` | `flag_id`, `params` | — | `FeatureFlag` |
| `delete_feature_flag` | :5888 | 2 | `async delete_feature_flag(flag_id): Promise<void>` | `flag_id` | — | `None` |

**FEATURE FLAG LIFECYCLE (Phase 025)** (3 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `archive_feature_flag` | :5913 | 1 | `async archive_feature_flag(flag_id): Promise<void>` | `flag_id` | — | `None` |
| `restore_feature_flag` | :5934 | 1 | `async restore_feature_flag(flag_id): Promise<FeatureFlag>` | `flag_id` | — | `FeatureFlag` |
| `duplicate_feature_flag` | :5963 | 1 | `async duplicate_feature_flag(flag_id): Promise<FeatureFlag>` | `flag_id` | — | `FeatureFlag` |

**FEATURE FLAG OPERATIONS (Phase 025)** (3 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `set_flag_test_users` | :5996 | 2 | `async set_flag_test_users(flag_id, params): Promise<void>` | `flag_id`, `params` | — | `None` |
| `get_flag_history` | :6021 | 2 | `async get_flag_history(flag_id, page, page_size): Promise<FlagHistoryResponse>` | `flag_id` | `page`, `page_size` | `FlagHistoryResponse` |
| `get_flag_limits` | :6065 | 2 | `async get_flag_limits(): Promise<FlagLimitsResponse>` | — | — | `FlagLimitsResponse` |

**EXPERIMENT CRUD (Phase 025)** (5 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_experiments` | :6096 | 4 | `async list_experiments(include_archived): Promise<list[Experiment]>` | — | `include_archived` | `list[Experiment]` |
| `create_experiment` | :6125 | 1 | `async create_experiment(params): Promise<Experiment>` | `params` | — | `Experiment` |
| `get_experiment` | :6158 | 2 | `async get_experiment(experiment_id): Promise<Experiment>` | `experiment_id` | — | `Experiment` |
| `update_experiment` | :6189 | 1 | `async update_experiment(experiment_id, params): Promise<Experiment>` | `experiment_id`, `params` | — | `Experiment` |
| `delete_experiment` | :6227 | 1 | `async delete_experiment(experiment_id): Promise<void>` | `experiment_id` | — | `None` |

**EXPERIMENT LIFECYCLE (Phase 025)** (3 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `launch_experiment` | :6252 | 1 | `async launch_experiment(experiment_id): Promise<Experiment>` | `experiment_id` | — | `Experiment` |
| `conclude_experiment` | :6279 | 2 | `async conclude_experiment(experiment_id, params): Promise<Experiment>` | `experiment_id` | `params` | `Experiment` |
| `decide_experiment` | :6315 | 1 | `async decide_experiment(experiment_id, params): Promise<Experiment>` | `experiment_id`, `params` | — | `Experiment` |

**EXPERIMENT MANAGEMENT (Phase 025)** (4 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `archive_experiment` | :6354 | 1 | `async archive_experiment(experiment_id): Promise<void>` | `experiment_id` | — | `None` |
| `restore_experiment` | :6375 | 1 | `async restore_experiment(experiment_id): Promise<Experiment>` | `experiment_id` | — | `Experiment` |
| `duplicate_experiment` | :6402 | 2 | `async duplicate_experiment(experiment_id, params): Promise<Experiment>` | `experiment_id`, `params` | — | `Experiment` |
| `list_erf_experiments` | :6441 | 1 | `async list_erf_experiments(): Promise<list[dict[str, Any]]>` | — | — | `list[dict[str, Any]]` |

### Scope / Python sources

`workspace.py:5751-6461` (HEAD): flags CRUD/lifecycle/operations
:5753-6248, experiments CRUD/lifecycle/management :6250-6461 (api-map order;
re-read the exact bodies — lifecycle members like `launch_experiment` /
`conclude_experiment` / `decide_experiment` carry decision-payload shaping
beyond a bare forward). Delegates: `services/entities/flags.ts` +
`experiments.ts` (B4-C4).

### TS homes / Layer-3 / consumers / harness / done

- Home: `workspace-members/flags-experiments.ts` + the B6-W4 section.
- Layer-3: `tests/unit/test_workspace_flags.py` →
  `test/workspace/workspace-flags.test.ts`;
  `tests/unit/test_workspace_experiments.py` →
  `test/workspace/workspace-experiments.test.ts` (WHOLE files).
- R10.10: end users; bindings §11.
- R10.9 `throwaway/b6-w4/`: delegation probes + status branches for
  `get_feature_flag` (200/404) and `decide_experiment` (200/400/422); edge
  set through flag/experiment params; every facade-local error branch.
- Done: 23 members live; tests green; `npm run check`; notes
  `B6-W4-notes.md`; commit.

---

## §7 Packet W5 — annotations + webhooks + alerts (opus; parallel after W1)

### Members (23) + api-map rows (PASTED)

**Annotations (Phase 026)** (7 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_annotations` | :6466 | 4 | `async list_annotations(from_date, to_date, tags): Promise<list[Annotation]>` | — | `from_date`, `to_date`, `tags` | `list[Annotation]` |
| `create_annotation` | :6507 | 2 | `async create_annotation(params): Promise<Annotation>` | `params` | — | `Annotation` |
| `get_annotation` | :6539 | 3 | `async get_annotation(annotation_id): Promise<Annotation>` | `annotation_id` | — | `Annotation` |
| `update_annotation` | :6567 | 1 | `async update_annotation(annotation_id, params): Promise<Annotation>` | `annotation_id`, `params` | — | `Annotation` |
| `delete_annotation` | :6600 | 2 | `async delete_annotation(annotation_id): Promise<void>` | `annotation_id` | — | `None` |
| `list_annotation_tags` | :6621 | 2 | `async list_annotation_tags(): Promise<list[AnnotationTag]>` | — | — | `list[AnnotationTag]` |
| `create_annotation_tag` | :6649 | 1 | `async create_annotation_tag(params): Promise<AnnotationTag>` | `params` | — | `AnnotationTag` |

**Webhook CRUD (Phase 026)** (5 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_webhooks` | :6685 | 3 | `async list_webhooks(): Promise<list[ProjectWebhook]>` | — | — | `list[ProjectWebhook]` |
| `create_webhook` | :6713 | 3 | `async create_webhook(params): Promise<WebhookMutationResult>` | `params` | — | `WebhookMutationResult` |
| `update_webhook` | :6746 | 1 | `async update_webhook(webhook_id, params): Promise<WebhookMutationResult>` | `webhook_id`, `params` | — | `WebhookMutationResult` |
| `delete_webhook` | :6782 | 2 | `async delete_webhook(webhook_id): Promise<void>` | `webhook_id` | — | `None` |
| `test_webhook` | :6803 | 2 | `async test_webhook(params): Promise<WebhookTestResult>` | `params` | — | `WebhookTestResult` |

**Alert CRUD (Phase 026)** (11 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_alerts` | :6839 | 4 | `async list_alerts(bookmark_id, skip_user_filter): Promise<list[CustomAlert]>` | — | `bookmark_id`, `skip_user_filter` | `list[CustomAlert]` |
| `create_alert` | :6876 | 1 | `async create_alert(params): Promise<CustomAlert>` | `params` | — | `CustomAlert` |
| `get_alert` | :6914 | 2 | `async get_alert(alert_id): Promise<CustomAlert>` | `alert_id` | — | `CustomAlert` |
| `update_alert` | :6942 | 1 | `async update_alert(alert_id, params): Promise<CustomAlert>` | `alert_id`, `params` | — | `CustomAlert` |
| `delete_alert` | :6973 | 1 | `async delete_alert(alert_id): Promise<void>` | `alert_id` | — | `None` |
| `bulk_delete_alerts` | :6994 | 1 | `async bulk_delete_alerts(ids): Promise<void>` | `ids` | — | `None` |
| `get_alert_count` | :7015 | 2 | `async get_alert_count(alert_type): Promise<AlertCount>` | — | `alert_type` | `AlertCount` |
| `get_alert_history` | :7044 | 2 | `async get_alert_history(alert_id, page_size, next_cursor, …): Promise<AlertHistoryResponse>` | `alert_id` | `page_size`, `next_cursor`, `previous_cursor` | `AlertHistoryResponse` |
| `test_alert` | :7090 | 1 | `async test_alert(params): Promise<Record<string, unknown>>` | `params` | — | `dict[str, Any]` |
| `get_alert_screenshot_url` | :7121 | 1 | `async get_alert_screenshot_url(gcs_key): Promise<AlertScreenshotResponse>` | `gcs_key` | — | `AlertScreenshotResponse` |
| `validate_alerts_for_bookmark` | :7151 | 1 | `async validate_alerts_for_bookmark(params): Promise<ValidateAlertsForBookmarkResponse>` | `params` | — | `ValidateAlertsForBookmarkResponse` |

### Scope / Python sources

`workspace.py:6462-7196` (HEAD): annotations :6466-6679 (incl. the tag pair),
webhooks :6683-6833, alerts :6837-7196 (11 members — `test_alert`,
`get_alert_screenshot_url`, `validate_alerts_for_bookmark` have
more-than-forward bodies; port branch-for-branch). Delegates:
`services/entities/{annotations,webhooks,alerts}.ts` (B4-C4).

### TS homes / Layer-3 / consumers / harness / done

- Home: `workspace-members/annotations-webhooks-alerts.ts` + the B6-W5 section.
- Layer-3: `tests/unit/test_workspace_annotations.py`,
  `tests/unit/test_workspace_webhooks.py`,
  `tests/unit/test_workspace_alerts.py` (WHOLE files) →
  `test/workspace/workspace-{annotations,webhooks,alerts}.test.ts`.
- R10.10: end users; bindings §11.
- R10.9 `throwaway/b6-w5/`: delegation probes + status branches for
  `create_annotation` (200/400) and `test_webhook` (200/429-exhausted/500);
  edge set (dates in annotations are STRINGS end-to-end — watchlist #5);
  every facade-local error branch.
- Done: 23 members live; tests green; `npm run check`; notes
  `B6-W5-notes.md`; commit.

---

## §8 Packet W6 — lexicon data definitions + tracking & history (opus; parallel after W1)

### Members (15) + api-map rows (PASTED)

**Data Governance — Data Definitions / Lexicon (Phase 027)** (11 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `get_event_definitions` | :7201 | 4 | `async get_event_definitions(names): Promise<list[EventDefinition]>` | — | `names` | `list[EventDefinition]` |
| `update_event_definition` | :7235 | 2 | `async update_event_definition(event_name, params): Promise<EventDefinition>` | `event_name`, `params` | — | `EventDefinition` |
| `delete_event_definition` | :7272 | 1 | `async delete_event_definition(event_name): Promise<void>` | `event_name` | — | `None` |
| `bulk_update_event_definitions` | :7293 | 2 | `async bulk_update_event_definitions(params): Promise<list[EventDefinition]>` | `params` | — | `list[EventDefinition]` |
| `get_property_definitions` | :7331 | 4 | `async get_property_definitions(names, resource_type): Promise<list[PropertyDefinition]>` | — | `names`, `resource_type` | `list[PropertyDefinition]` |
| `update_property_definition` | :7375 | 3 | `async update_property_definition(property_name, params): Promise<PropertyDefinition>` | `property_name`, `params` | — | `PropertyDefinition` |
| `bulk_update_property_definitions` | :7412 | 3 | `async bulk_update_property_definitions(params): Promise<list[PropertyDefinition]>` | `params` | — | `list[PropertyDefinition]` |
| `list_lexicon_tags` | :7460 | 3 | `async list_lexicon_tags(): Promise<list[LexiconTag]>` | — | — | `list[LexiconTag]` |
| `create_lexicon_tag` | :7502 | 2 | `async create_lexicon_tag(params): Promise<LexiconTag>` | `params` | — | `LexiconTag` |
| `update_lexicon_tag` | :7530 | 1 | `async update_lexicon_tag(tag_id, params): Promise<LexiconTag>` | `tag_id`, `params` | — | `LexiconTag` |
| `delete_lexicon_tag` | :7561 | 1 | `async delete_lexicon_tag(tag_name): Promise<void>` | `tag_name` | — | `None` |

**Data Governance — Tracking & History (Phase 027)** (4 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `get_tracking_metadata` | :8530 | 1 | `async get_tracking_metadata(event_name): Promise<Record<string, unknown>>` | `event_name` | — | `dict[str, Any]` |
| `get_event_history` | :8558 | 2 | `async get_event_history(event_name): Promise<list[dict[str, Any]]>` | `event_name` | — | `list[dict[str, Any]]` |
| `get_property_history` | :8585 | 1 | `async get_property_history(property_name, entity_type): Promise<list[dict[str, Any]]>` | `property_name`, `entity_type` | — | `list[dict[str, Any]]` |
| `export_lexicon` | :8618 | 3 | `async export_lexicon(export_types): Promise<Record<string, unknown>>` | — | `export_types` | `dict[str, Any]` |

### Scope / Python sources

`workspace.py:7197-7581` (HEAD; lexicon defs + tags, "---- Tags ----" at
:7458) and `workspace.py:8527-8649` (Tracking & History: `get_tracking_metadata`,
`get_event_history`, `get_property_history`, `export_lexicon`). Delegates:
`services/entities/lexicon.ts` (B4-C5).

### TS homes / Layer-3 / consumers / harness / done

- Home: `workspace-members/lexicon-tracking.ts` + the B6-W6 section.
- Layer-3 (class-split of `tests/unit/test_workspace_data_governance.py`,
  1,842 lines): the lexicon + tags classes (`TestGetEventDefinitions` :259
  through `TestDeleteLexiconTag` :604) + the tracking/history classes
  (`TestGetTrackingMetadata` :1190, `TestGetEventHistory` :1217,
  `TestGetPropertyHistory` :1256, `TestExportLexicon` :1287) →
  `test/workspace/lexicon-tracking.test.ts`.
- R10.10: end users; bindings §11.
- R10.9 `throwaway/b6-w6/`: delegation probes + status branches for
  `get_event_definitions` (200/404) and `export_lexicon` (200/500); edge set
  through definition-update payloads; every facade-local error branch.
- Done: 15 members live; tests green; `npm run check`; notes
  `B6-W6-notes.md`; commit.

---

## §9 Packet W7 — drop filters + custom properties + lookup tables + custom events (opus; parallel after W1)

### Members (24) + api-map rows (PASTED)

**Data Governance — Drop Filters (Phase 027)** (5 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_drop_filters` | :7586 | 3 | `async list_drop_filters(): Promise<list[DropFilter]>` | — | — | `list[DropFilter]` |
| `create_drop_filter` | :7613 | 1 | `async create_drop_filter(params): Promise<list[DropFilter]>` | `params` | — | `list[DropFilter]` |
| `update_drop_filter` | :7648 | 1 | `async update_drop_filter(params): Promise<list[DropFilter]>` | `params` | — | `list[DropFilter]` |
| `delete_drop_filter` | :7682 | 1 | `async delete_drop_filter(drop_filter_id): Promise<list[DropFilter]>` | `drop_filter_id` | — | `list[DropFilter]` |
| `get_drop_filter_limits` | :7711 | 2 | `async get_drop_filter_limits(): Promise<DropFilterLimitsResponse>` | — | — | `DropFilterLimitsResponse` |

**Data Governance — Custom Properties (Phase 027)** (6 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_custom_properties` | :7742 | 3 | `async list_custom_properties(): Promise<list[CustomProperty]>` | — | — | `list[CustomProperty]` |
| `create_custom_property` | :7791 | 1 | `async create_custom_property(params): Promise<CustomProperty>` | `params` | — | `CustomProperty` |
| `get_custom_property` | :7831 | 2 | `async get_custom_property(property_id): Promise<CustomProperty>` | `property_id` | — | `CustomProperty` |
| `update_custom_property` | :7861 | 1 | `async update_custom_property(property_id, params): Promise<CustomProperty>` | `property_id`, `params` | — | `CustomProperty` |
| `delete_custom_property` | :7897 | 1 | `async delete_custom_property(property_id): Promise<void>` | `property_id` | — | `None` |
| `validate_custom_property` | :7918 | 1 | `async validate_custom_property(params): Promise<Record<string, unknown>>` | `params` | — | `dict[str, Any]` |

**Data Governance — Lookup Tables (Phase 027)** (9 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_lookup_tables` | :7957 | 4 | `async list_lookup_tables(data_group_id): Promise<list[LookupTable]>` | — | `data_group_id` | `list[LookupTable]` |
| `upload_lookup_table` | :7989 | **0** | `async upload_lookup_table(params, poll_interval, max_poll_seconds): Promise<LookupTable>` | `params` | `poll_interval`, `max_poll_seconds` | `LookupTable` |
| `mark_lookup_table_ready` | :8146 | 1 | `async mark_lookup_table_ready(params): Promise<LookupTable>` | `params` | — | `LookupTable` |
| `get_lookup_upload_url` | :8190 | 3 | `async get_lookup_upload_url(content_type): Promise<LookupTableUploadUrl>` | `content_type` | — | `LookupTableUploadUrl` |
| `get_lookup_upload_status` | :8222 | 1 | `async get_lookup_upload_status(upload_id): Promise<Record<string, unknown>>` | `upload_id` | — | `dict[str, Any]` |
| `update_lookup_table` | :8247 | 1 | `async update_lookup_table(data_group_id, params): Promise<LookupTable>` | `data_group_id`, `params` | — | `LookupTable` |
| `delete_lookup_tables` | :8281 | 1 | `async delete_lookup_tables(data_group_ids): Promise<void>` | `data_group_ids` | — | `None` |
| `download_lookup_table` | :8302 | 2 | `async download_lookup_table(data_group_id, file_name, limit): Promise<bytes>` | `data_group_id` | `file_name`, `limit` | `bytes` |
| `get_lookup_download_url` | :8337 | 1 | `async get_lookup_download_url(data_group_id): Promise<string>` | `data_group_id` | — | `str` |

**Data Governance — Custom Events (Phase 027)** (4 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `create_custom_event` | :8366 | 4 | `async create_custom_event(params): Promise<CustomEvent>` | `params` | — | `CustomEvent` |
| `list_custom_events` | :8409 | 3 | `async list_custom_events(): Promise<list[EventDefinition]>` | — | — | `list[EventDefinition]` |
| `update_custom_event` | :8436 | 4 | `async update_custom_event(custom_event_id, params): Promise<EventDefinition>` | `custom_event_id`, `params` | — | `EventDefinition` |
| `delete_custom_event` | :8494 | 2 | `async delete_custom_event(custom_event_id): Promise<void>` | `custom_event_id` | — | `None` |

### Scope / Python sources

`workspace.py:7583-8525` (HEAD): drop filters :7583-7737, custom properties
:7739-7952, lookup tables :7954-8361, custom events :8363-8525. Delegates:
`services/entities/{drop-filters,custom-properties,lookup-tables,custom-events}.ts`
(B4-C5).

### W7-D1 — `upload_lookup_table` file I/O seam (arbiter-visible)

`upload_lookup_table` (`workspace.py:7989-8300`; ZERO vectors) is a
multi-step orchestrator — `get_lookup_upload_url` → `upload_to_signed_url` →
`register_lookup_table` → async poll (`get_lookup_upload_status` /
`mark_lookup_table_ready`) — and reads the CSV from disk:
`Path(params.file_path).read_bytes()` at :8044. `packages/core` is
runtime-agnostic (no `node:fs`). **Decision**: inject
`readFile?: (path: string) => Promise<Uint8Array>` via `WorkspaceOptions`
(default throws a coded `MixpanelHeadlessError`, `TODO(port): B8` wires
`node:fs` in `packages/node`); the poll loop uses the existing injectable
`sleep` seam (R6.3 — `poll_interval`/`max_poll_seconds` stay SECONDS in the
options bag under their Python names, converted to ms at the one sleep call,
R2.12). Layer-3 `TestUploadLookupTable` (:1423) uses tmp files — the TS
translation injects a fake `readFile`. The client-side five wire methods it
orchestrates are ALL live (B4-C5, `lookup-tables.ts`); the facade re-uses
them by name (R10.8).

### TS homes / Layer-3 / consumers / harness / done

- Home: `workspace-members/governance-data.ts` + the B6-W7 section.
- Layer-3 (class-split of `test_workspace_data_governance.py`): drop-filter
  classes (:623-:743), custom-property classes (:771-:938), custom-event
  classes (:939-:1189), lookup-table classes (:1363-:1848) →
  `test/workspace/governance-data.test.ts` (or split into two files at the
  translator's discretion — header cites either way).
- R10.10: end users; bindings §11.
- R10.9 `throwaway/b6-w7/`: delegation probes + status branches for
  `create_drop_filter` (200/400) and `download_lookup_table` (200/404/500);
  the upload orchestration path replayed over canned interactions covering
  sync-complete, async-poll-then-ready, and poll-timeout branches; edge set;
  every facade-local error branch incl. the `readFile` default throw.
- Done: 24 members live; tests green; `npm run check`; notes
  `B6-W7-notes.md`; commit.

---

## §10 Packet W8 — schema registry + enforcement + audit + anomalies + deletion requests (opus; parallel after W1)

### Members (20) + api-map rows (PASTED)

**Schema Registry CRUD (Phase 028)** (6 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_schema_registry` | :8654 | 7 | `async list_schema_registry(entity_type): Promise<list[SchemaEntry]>` | — | `entity_type` | `list[SchemaEntry]` |
| `create_schema` | :8689 | 3 | `async create_schema(entity_type, entity_name, schema_json): Promise<Record<string, unknown>>` | `entity_type`, `entity_name`, `schema_json` | — | `dict[str, Any]` |
| `create_schemas_bulk` | :8722 | 4 | `async create_schemas_bulk(params): Promise<BulkCreateSchemasResponse>` | `params` | — | `BulkCreateSchemasResponse` |
| `update_schema` | :8760 | 3 | `async update_schema(entity_type, entity_name, schema_json): Promise<Record<string, unknown>>` | `entity_type`, `entity_name`, `schema_json` | — | `dict[str, Any]` |
| `update_schemas_bulk` | :8793 | 4 | `async update_schemas_bulk(params): Promise<list[BulkPatchResult]>` | `params` | — | `list[BulkPatchResult]` |
| `delete_schemas` | :8830 | 6 | `async delete_schemas(entity_type, entity_name): Promise<DeleteSchemasResponse>` | — | `entity_type`, `entity_name` | `DeleteSchemasResponse` |

**Schema Enforcement (Phase 028)** (5 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `get_schema_enforcement` | :8879 | 2 | `async get_schema_enforcement(fields): Promise<SchemaEnforcementConfig>` | — | `fields` | `SchemaEnforcementConfig` |
| `init_schema_enforcement` | :8913 | 1 | `async init_schema_enforcement(params): Promise<Record<string, unknown>>` | `params` | — | `dict[str, Any]` |
| `update_schema_enforcement` | :8943 | 1 | `async update_schema_enforcement(params): Promise<Record<string, unknown>>` | `params` | — | `dict[str, Any]` |
| `replace_schema_enforcement` | :8973 | 1 | `async replace_schema_enforcement(params): Promise<Record<string, unknown>>` | `params` | — | `dict[str, Any]` |
| `delete_schema_enforcement` | :9005 | 1 | `async delete_schema_enforcement(): Promise<Record<string, unknown>>` | — | — | `dict[str, Any]` |

**Data Auditing (Phase 028)** (2 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `run_audit` | :9029 | 3 | `async run_audit(): Promise<AuditResponse>` | — | — | `AuditResponse` |
| `run_audit_events_only` | :9069 | 2 | `async run_audit_events_only(): Promise<AuditResponse>` | — | — | `AuditResponse` |

**Data Volume Anomalies (Phase 028)** (3 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_data_volume_anomalies` | :9110 | 3 | `async list_data_volume_anomalies(query_params): Promise<list[DataVolumeAnomaly]>` | — | `query_params` | `list[DataVolumeAnomaly]` |
| `update_anomaly` | :9143 | 1 | `async update_anomaly(params): Promise<Record<string, unknown>>` | `params` | — | `dict[str, Any]` |
| `bulk_update_anomalies` | :9171 | 1 | `async bulk_update_anomalies(params): Promise<Record<string, unknown>>` | `params` | — | `dict[str, Any]` |

**Event Deletion Requests (Phase 028)** (4 members):

| member | py def (HEAD) | vec | api-map `ts_signature` | params | kwonly | returns |
|---|---|---|---|---|---|---|
| `list_deletion_requests` | :9204 | 3 | `async list_deletion_requests(): Promise<list[EventDeletionRequest]>` | — | — | `list[EventDeletionRequest]` |
| `create_deletion_request` | :9229 | 1 | `async create_deletion_request(params): Promise<list[EventDeletionRequest]>` | `params` | — | `list[EventDeletionRequest]` |
| `cancel_deletion_request` | :9268 | 2 | `async cancel_deletion_request(request_id): Promise<list[EventDeletionRequest]>` | `request_id` | — | `list[EventDeletionRequest]` |
| `preview_deletion_filters` | :9296 | 2 | `async preview_deletion_filters(params): Promise<list[dict[str, Any]]>` | `params` | — | `list[dict[str, Any]]` |

### Scope / Python sources

`workspace.py:8651-9331` (HEAD): schema registry :8651-8874, schema
enforcement :8876-9024, data auditing :9026-9105, data volume anomalies
:9107-9199, event deletion requests :9201-9331. Delegates:
`services/entities/{schemas,schema-enforcement,audit,anomalies,deletion-requests}.ts`
(B4-C5). `run_audit`/`run_audit_events_only` and `preview_deletion_filters`
(:9296) carry composite bodies — port branch-for-branch.

### TS homes / Layer-3 / consumers / harness / done

- Home: `workspace-members/schemas-audit.ts` + the B6-W8 section.
- Layer-3: `tests/unit/test_workspace_schemas.py` (WHOLE, 6 classes) →
  `test/workspace/workspace-schemas.test.ts`;
  `tests/unit/test_workspace_governance.py` (WHOLE, 14 classes :194-:731) →
  `test/workspace/workspace-governance.test.ts`.
- R10.10: end users; bindings §11.
- R10.9 `throwaway/b6-w8/`: delegation probes + status branches for
  `create_schema` (200/400/422) and `run_audit` (200/500); edge set; every
  facade-local error branch.
- Done: 20 members live; tests green; `npm run check`; notes
  `B6-W8-notes.md`; commit.

---
## §11 Binding plan (the fable BIND task — P3-2 b′, single task after W1–W8)

1. **Names to bind: the 154 REGISTRY-COVERED member names** — all B6 members
   except the four read-only properties (`account`, `project`, `workspace`,
   `session`): the recorder's mechanical enumeration registers **functions
   only** (`registry.py:117-158` — `inspect.isfunction` skips `property`
   objects), so those four have no api names, no vectors, and no binding;
   their lock is W1's Layer-3. Kinds per `registry.py:99-104`: `use` and
   `close` are **wire_state** (replay as `call.setup[]` re-execution only —
   no return-shape contract; `clear_discovery_cache`, the third
   `_WORKSPACE_STATE_NAMES` entry, was bound at B5); the other 152 are
   **wire_api**. Bind ALL of them, including the 16 zero-vector method names
   (§1 table minus the 4 properties) — the flip's straggler ratchet and any
   future authored vector need the names resolvable (B5 §6.1 precedent).
2. **`workspace.me` closes the B4 dagger holdback.** Binding `workspace.me`
   through the REAL facade (which installs the W1 `setWorkspaceResolver`
   wiring and populates the in-memory `MeCacheStore`) makes the carried
   vector's setup executable; the measured `api_client.resolve_workspace_id`
   call then resolves from the me view over the SHARED client instance
   (§0.6 memoization — the facade must be built over `clientFromSession`'s
   memoized client or the setup populates a cache the measured call never
   sees). Verified vector id (§1). Expected: UNPORTED → PASS at the gate
   flip; it is the +1 in the 354 gate delta.
3. **Module layout**: extend `conformance-runner/src/wire-workspace.ts`'s
   registration surface with new sibling modules (recommend
   `wire-workspace-entities.ts` for W2–W8 names and folding the W1 names
   into `wire-workspace.ts` beside `workspaceFromSession`) — one
   registration point shared with oracle-ts, same memoized
   `workspaceFromSession(context)` twin (P3-5 §1; contract doc at
   `wire-workspace.ts:1-35`).
4. **Binding honesty (P3-5 rule 3)**: every binding calls the REAL
   `Workspace` member the recorder wrapped (`registry.py` targets
   `workspace:Workspace.<name>`) — never `client.<name>` directly, never a
   re-derived flatten. The only adaptations are kwarg→options plumbing and
   the established output-codec twins (`wire-workspace.ts:28-35` — float
   tokens, `$type` datetime tags, `toVectorPayload()` where the S-shards
   defined it; entity models serialize via the Phase-2
   `toVectorPayload()`/`toJSON()` walk). Arbiter verifies per shard.
5. **Oracle registration: NOTHING new.** All 154 names are wire-kind —
   B6 adds ZERO builder-kind apis, so there are no new oracle strategies in
   `conformance/differential/strategies.py` and the gate's mechanical
   oracle probe has an EMPTY new-name set (wire names are exempt,
   playbook P3-2e item 3). State this in the BIND notes so the gate task
   doesn't hunt for missing strategies. The differential full-suite
   regression (§12.3) still re-runs over the cumulative surface.
6. **Vector failures surfaced here are the owning MODULE task's attempt-1
   failure** (P3-3 escalation: retry once on fable with context; two misses
   abort). After (b′) lands, each shard's R10.9 harness (§3–§10) runs at the
   module tier if not already run.

---

## §12 Gate flip spec (fable gate task — P3-2 e; REFEREES REQUIRED, P3-7)

1. **`batch-status.ts` changes, ONE commit with the checkpoint**
   (playbook P3-5 B6-gate rule, `:660-662`):
   - REPLACE the 44 B5 exact-name `workspace.<member>` → `done` entries
     (`batch-status.ts:85-134`) AND the `workspace.list_bookmarks_v2` →
     `pending` override (`:111`) AND the `workspace.` → `pending` row
     (`:81`) with the single collapsed entry **`workspace.` → `done`**
     (longest-prefix keeps the states equivalent for every B5 name;
     the override REMOVAL is the B5 §7.1 forward note landing here).
   - Update the file's doc comment (`:43-59`) — the B5-era collision notes
     describe a table that no longer exists.
   - **Standing collision assertion over the FINAL state** (playbook
     `:637-639`): scan every still-pending corpus api name for `startsWith`
     hits against the post-flip table. After this gate the only pending
     prefixes are `region_probe.` and `oauth_flow.` (measured names:
     `region_probe.probe_region` ×14, `oauth_flow.refresh_tokens` ×7);
     assert zero of them prefix-match any `done` entry and that no
     `workspace.*` corpus name remains pending. Record the scan output in
     the gate notes.
   - Batch-status unit suite (full-corpus prefix coverage) stays green.
2. **Conformance checkpoint**: `npm run conformance` → expect exactly
   **3,230 PASS / 0 FAIL / 21 UNPORTED** (2,876 + the gate delta 354; the
   21 = 14 `region_probe.` + 7 `oauth_flow.`). FAIL=0 is a hard gate.
   Archive the report JSON → `context/phase3/reports/2026-08-<day>-b6-gate.json`;
   commit both repos (TS gate commit on `main`; Python docs/report commit on
   the support branch).
3. **Oracle probe + differential regression**: the probe's new-name set is
   EMPTY (§11.5 — all-wire batch; wire names exempt per
   `oracle_py/server.py:414-418` semantics). Run the differential
   full-suite regression anyway (cumulative surface, fresh seeds,
   ≥500/family): zero unexplained divergences beyond the standing
   documented classes (#9/#10 exclusions, #12 residuals); RUN record
   appended to `differential/oracle/RUN.md`.
4. **Referees (a)+(b) — REQUIRED at this gate** (P3-7: B3 and B6 are the
   bookmark-touching batches): re-run (a) the bookmark.json ajv validator
   and (b) the bookmark_parser round-trip harness over the refreshed
   `FEED_SLOTS` feed (D15a data-driven rule, `B3-notes.md:65`; the B5 gate
   added `workspace.build_params`). W3's `create_bookmark`/`update_bookmark`
   pass through ALREADY-BUILT params (construction stayed B3/B5), so no new
   feed slot is expected — but if W3's shard notes record any surface that
   EMITS a bookmark payload, add it to the feed before the run. Known
   standing REJECTs carried from B3 (frequency-filter clause shape,
   dataGroupId int threading — open R10.7 items, `B3-notes.md:63`) are
   EXPECTED and do not block; any NEW reject does.
5. **UNPORTED-probe re-anchor retirement (B5 §6.7/§8 forward note)**: both
   `conformance-runner/test/runner.test.ts:148-154` and
   `differential/test/oracle-protocol.test.ts:298-314` anchor their
   UNPORTED/unknown-api exemplars on `workspace.me`, which this gate flips
   to done. Re-anchor both to **`region_probe.probe_region`** (pending until
   B7 by construction), comments updated in place; at the B8 gate the
   pattern retires entirely (no pending names remain — that gate's author
   converts the probes to synthetic never-registered names or deletes them,
   noted here so the churn convention ends deliberately).
6. `npm run check` green (TS); `just check` green (Python — report/notes
   commits touch the repo). Remove `throwaway/b6-w*/` after arbiter
   sign-off. Finalize `context/phase3/notes/B6-notes.md`.

---

## §13 Deferral ledger

### Inbound (every B5 §8 outbound item + older cited deferrals, placed)

| Inbound deferral (source cite) | Placed |
|---|---|
| `use()`/`close()`/`[Symbol.asyncDispose]` UNPORTED stubs (`workspace.ts:699-737`; B5 §8) | W1 (§3) |
| `workspace.me` + the B4 dagger holdback (B5 §6.8; P3-1 †) | W1 implements (§3.3); BIND closes (§11.2); gate counts it (+1 → 354) |
| `stream_events`/`stream_profiles`/`api` facade veneer decision (B5 §8) | W1-D3 (§3) — CLOSED: R6.6 `yield*` veneers + `get api()` |
| `TestDiscoveryCacheAcrossUse` (`test_query_workspace_scoping.py`; B4-C1 → B5 §8) | W1 Layer-3 (§3, R6.2 block) |
| `workspace.list_bookmarks_v2` pending-override removal (B5 §7.1, `batch-status.ts:111`) | Gate §12.1 |
| UNPORTED-probe re-anchor lands on a B6 name (B5 §6.7/§8) | Gate §12.5 → `region_probe.probe_region` |
| `response-validation.ts:22-27` `TODO(port)` owner = B6 (B5 §8 "A-F3" row) | W2–W8 Layer-3 CRUD suites lock additional non-missing pydantic wording; triage the marker at the W3 review (leave it open only with a re-scoped owner + cite) |
| Discrepancy #10 re-examination "at the B6-W3 review" (playbook `:905`) | W3 (§5) named duty |
| Referee re-run at the bookmark-touching gate (P3-7) | Gate §12.4 |

### Outbound (created by B6, for the B7/B8 packet authors)

| Outbound deferral | Owner |
|---|---|
| `ResolverSeams` default-throw implementations (`UNPORTED_RESOLVER_SEAM`) — `resolveSession`/`getAccount`/`resolveProjectAxis`/`envWorkspaceId` real implementations | B7 (interface shape fixed by W1-D1) |
| `persistActive` seam (`ConfigManager.apply_session`, `workspace.py:696-722`) | B8 (config I/O) via B7 orchestration |
| `MeCacheStore` on-disk twin (`me.py:413-607`) | B8-N2 |
| `readFile` seam default (W7-D1) → `node:fs` wiring in `packages/node` | B8 |
| `test_workspace_use.py` resolver classes (§3 table) | B7 |
| `test_workspace_init.py` resolver classes / `TestBridgeTokenMaterialization` | B7 / B8 |
| `test_workspace.py::TestCredentialResolution` | B7 |
| `test_042_edge_cases.py` WHOLE (playbook misassignment — §14.1): 4 classes → B7, 3 → B8, `TestCliExitCodes`+`TestSecretLeakage` → B7 author decides (CLI outside library scope; document) | B7/B8 |
| UNPORTED-probe pattern retirement at the LAST flip | B8 gate |

---

## §14 Cautions (file:line cited) + discrepancy notes

1. **Playbook misassignment — `test_042_edge_cases.py`** (B5
   transform-tests precedent): the playbook B6 row lists it as "(facade
   axes)", but the file contains zero `Workspace(` call sites (verified
   2026-08-16) — all 9 classes are B7/B8 surfaces. Ledger §13; no B6
   translation. Similarly the row's `flow` suite
   (`tests/unit/test_workspace_flow.py`) was ALREADY translated at B5
   (`test/workspace/workspace-flow.test.ts`) — no B6 action.
2. **R6.2 identity invariant**: `ws.client` must be the SAME instance across
   `use()` (`workspace.py:672-677` delegates to `client.use`; locks:
   `test_workspace_use.py:132` `TestHTTPTransportPreservation`,
   `tests/integration/test_cross_project_iteration.py` `id()` equality).
   Facade NEVER constructs a second client on switch.
3. **`use()` cache-clear block** (`workspace.py:679-693`): `_discovery`,
   `_live_query`, `_me_service`, `_replays_svc` all reset + `_account_name`
   / `_initial_workspace_id` refresh — and the `setWorkspaceResolver`
   re-install (`:787` runs at client-construction wiring in Python; W1 must
   keep the resolver pointing at the CURRENT me-service after every swap).
4. **WS1 guard order**: `WS1_TARGET_MUTUALLY_EXCLUSIVE` raises BEFORE any
   resolution side effects (`workspace.py:605-611`; the constructor twin at
   :455-465 is B7's).
5. **Entity params flattening**: `model_dump(exclude_none=True)` is
   RECURSIVE in pydantic v2 — the W1-D4 `modelDumpExcludeNone()` must
   recurse into nested models; `toJSON()` (`model-base.ts:495`) keeps
   `None`→`null` and is NOT a substitute. Absent-vs-null is
   vector-observable (R3.5).
6. **kwargs→options (R3.3/R3.8)**: required positionals stay positional
   (max 3; e.g. `update_cohort(cohort_id, params)`); keyword-only params →
   ONE trailing options bag; **options keys keep the Python spelling**
   (R3.4/R3.6 wire-shaped bags; the recorder replays kwargs BY NAME — B5
   Caution #8 precedent; `wire-workspace.ts` maps `call.input` keys
   verbatim). Python positional-with-default stays positional (R3.8).
7. **Facade members are uniformly async** (api-map `ts_signature`s) even
   where the Python body is sync-shaped; return `Promise<T>`
   (`AsyncIterable` direct for the W1-D3 veneers, R3.2).
8. **Empty-response guards**: `if raw is None: raise
   MixpanelHeadlessError("API returned empty response for X")` — default
   code `UNKNOWN_ERROR` (`exceptions.py` ctor default). Port the guard and
   the code; message text out of contract (R5.4) but ported anyway.
9. **No result pre-shaping below the facade** (B5 Caution #10 twin,
   `b4-packets.md:1083-1084` + `dashboards.ts:9-12`): the B4 entity methods
   return envelope products verbatim; Model construction happens ONLY in
   the W-shards via `validateResponseModel(s)` with the exact `endpoint=`
   string Python passes. Double-shaping fails vectors.
10. **Watchlist #13**: any `isinstance(x, dict)` in facade bodies ports via
    the prototype discrimination — reuse `isPlainRecord`
    (`services/entities/shared.ts`), never `typeof`-based checks.
11. **Watchlist #6 truthiness**: Python `if not raw` on lists/dicts/strings
    in facade guards → explicit emptiness checks, never `if (!x)`.
12. **Dates are strings** (watchlist #5): annotation/deletion-request date
    params stay `YYYY-MM-DD`/ISO strings end-to-end; never construct `Date`
    in the request path (the W1 `utcYmdFromEpochMs` precedent at
    `workspace.ts:2538+` is a RESULT-side exception already blessed at B5).
13. **R11.7**: any `int(str)` / `.strip()` in facade bodies (e.g. history
    cursor handling — check each) ports via `pythonInt`/`pythonStrip`;
    grep-audited at review.
14. **Zero-vector members flip `done` with everything else** at the §12.1
    collapse — their Layer-3 suites are the only lock (§1). The 3
    zero-vector B4 veneer members (`stream_events`/`stream_profiles`/`api`)
    were already inside flipped-`api_client.`-adjacent surface; their
    workspace.* names carry no vectors and no registry entries beyond the
    B4 client names — Layer-3 only.
15. **`workspace.list_bookmarks` (B5, 0 vectors) vs `list_bookmarks_v2`
    (W3, 7 vectors)**: distinct members; W3 implements `_v2` (the B5 member
    is already live); the flip collapse makes the B5-era override moot
    (§12.1). Never alias one to the other.
16. **Multipart/binary surfaces (W7)**: `upload_to_signed_url` PUTs raw CSV
    bytes to an EXTERNAL signed URL (`lookup-tables.ts:15,91-103`) — the
    facade orchestration must not route it through App-API headers;
    `download_lookup_table` returns bytes (`workspace.py:8302-8360`) —
    `Uint8Array` in TS, no UTF-8 decode.
17. **Business-context scope axis**: `get/set/clear_business_context` carry
    a `scope` param (`"project"` | `"organization"`) with organization-id
    derivation in the org branch — re-read `workspace.py:10405-10674` and
    port branch-for-branch; `clear_business_context` returns `None` in
    Python but its REQUEST side is the contract (registry hand-audit note,
    `registry.py:100-104`).
18. **`_validate_bookmark_params_schema` (W3, `workspace.py:5186-5245`)**
    consumes the B3 `bookmark_schema` surface — compose, never re-derive;
    Discrepancy #10's fuzz-domain exclusion (no integer-like unknown keys)
    applies to any W3-added fuzz.

---

## §15 Done-criteria (batch, restated per R10.5)

Per shard: §3–§10 done-criteria (files on disk + `tsc --strict` clean +
translated tests green + notes file). Batch: (b′) bindings live for all 154
registry names + all 353 vectors PASS + the dagger vector PASS (354 total
new) + review pair ×2 + arbiter GO per shard + referees (a)+(b) re-run clean
(§12.4) + gate steps §12 all green (`npm run check`, `just check`, report
archived at 3,230/0/21, batch-status collapsed with the collision assertion
recorded, `throwaway/b6-w*/` removed, notes finalized, commits local on the
correct branches). After this gate the ONLY pending prefixes are
`region_probe.` and `oauth_flow.`.
