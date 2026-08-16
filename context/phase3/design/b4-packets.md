# B4 design-lite packets — the wire client: api_client + pagination (P3-6 step 1)

**Status**: v1.0 · 2026-08-15 · fable design-lite packet for batch B4 (playbook P3-6 step 1,
sharding per P3-6 "B4 (6 tasks, fable)"). Location note: the orchestrator names
`context/phase3/design/b4-packets.md` (B2/B3 precedent); the playbook's generic path is
`context/phase3/packets/BX-packets.md` — this file is the packet of record for B4.
Every count below was MEASURED 2026-08-15 against corpus pin `70c904d`
(`conformance-runner/corpus.config.json`, sourceCommit `70c904dc598db2c74ca8429b603fa8bef19187ea`)
and Python source at support-branch HEAD (`ts-port/phase2-contract-support`;
`api_client.py` = 8,894 LOC, `pagination.py` = 288, `me.py` = 915, `client_metadata.py` = 73).
Baseline entering B4 (post-B3 gate, `context/phase3/reports/2026-08-15-b3-gate.json`):
**3,251 vectors = 1,528 PASS / 0 FAIL / 1,723 UNPORTED**.

**B4 gate expectation** (P3-1 row + † footnote): PASS grows by the gate delta **842**
(843 owned vectors minus the one carried vector — measured `api_client.resolve_workspace_id`
with setup `workspace.me`, a B6 member; it stays UNPORTED through the B4 and B5 gates and
first passes at B6). Post-gate report must read **2,370 PASS / 0 FAIL / 881 UNPORTED**.

**MODEL/TIER (P3-3, tiering revision 2026-08-15)**: every B4 task — module shards C1–C6,
bindings, harness, review pair, arbiter, gate — runs on **fable, effort ≤ high**, with the
R10.13 incremental protocol (skeleton file first, small frequent edits, running notes file
`context/phase3/notes/B4-<shard>-notes.md`, assemble the final answer from disk). NO
mutation testing `[SA1]`. Python via `uv`; bare `python` and the literal p-y-t-e-s-t string
are hook-blocked. LOCAL COMMITS ONLY in both repos.

---

## Shard map (measured; vector counts sum to exactly 843)

| Shard | Scope | api-index names | Vectors |
|---|---|---|---|
| C1 | Client core: construction/session axes/scoping/resolution + wire-enablement seam (`clientFromSession`) + me-selection logic | **11** | **81** |
| C2 | Query-host methods + streaming/export (the 3 B4 api-map members land here) | **24** | **317** |
| C3 | Entity CRUD wire methods: dashboards (+ blueprints/RCA) + bookmarks-v2 + cohorts-app | **38** | **78** |
| C4 | Flags + experiments + annotations + webhooks + alerts | **46** | **109** |
| C5 | Data governance (schemas, lexicon, drop filters, custom properties, lookup tables, custom events, schema enforcement, audit, anomalies, deletion requests) + business context + replays signing | **64** | **219** |
| C6 | `pagination.py` (`pagination.paginate_all`) | 0 (owns the `pagination.` prefix) | **39** |
| Σ | | **183** | **843** |

Arithmetic cross-check (measured from the corpus, this pin): `api_client.*` vectors total
**810**, of which 6 are `api_client._iter_jsonl_lines` (B0-owned, bound + flipped `done`
at B0 — NOT in the 183 api-index names and NOT in any C-shard). 810 − 6 = **804**
(= 81+317+78+109+219) + `pagination.paginate_all` **39** = **843**. The playbook B4 row's
"810 − 6 … + 39 = 843" reproduces exactly at this pin.

**Execution order**: **C1 FIRST — everything depends on it** (the client factory, the
`clientFromSession` seam, and the setup-api bindings that 96 vectors across all shards
need). After C1 lands: C2, C3, C4, C5 are mutually independent (disjoint Python line
ranges, disjoint TS homes, disjoint api names) — run in parallel. C6 requires only C1
(its module consumes `client.app_request`, a B0 export reached through the C1 client
object). The single shared merge point after C1 is the one-line spread each shard adds to
`createMixpanelClient`'s method assembly (see C1 packet §TS home); shards touch disjoint
lines there — coordinate by appending, never reordering.

### The 183-name assignment (every api-index `api_client.*` name exactly once)

Gate task verification is mechanical (P3-6): the union of the six lists below, sorted,
must equal `jq -r 'keys[]|select(startswith("api_client."))' corpus/api-index.json | sort`
(183 names, verified 2026-08-15 — zero missing, zero duplicates, zero extras).

**C1 (11)**: `app_request`†, `close`°, `maybe_scoped_path`†°, `request`,
`require_scoped_path`, `resolve_workspace`, `resolve_workspace_id`, `set_workspace_id`°,
`use`°, `list_workspaces`, `projects_metadata_index`.

† `app_request` and `maybe_scoped_path` are **B0-owned modules**
(`client/app-request.ts`, `client/scope.ts`) — C1 IMPORTS them by name (R10.8) and owns
only their **bindings** (31 and 0 measured vectors respectively; `maybe_scoped_path` is
setup-only). ° Zero measured vectors — setup-only names (`close` 8, `set_workspace_id` 97,
`use` 2, `maybe_scoped_path` 1 setup occurrences); they MUST still be bound (P3-5 §1
corollary: `gateApis`, `runner.ts:368-386`, short-circuits any vector whose setup api is
unbound).

**C2 (24)**: `export_events`, `export_profiles`, `export_profiles_page`, `engage_stats`,
`get_events`, `get_event_properties`, `get_property_values`, `list_funnels`,
`list_cohorts`, `get_top_events`, `event_counts`, `property_counts`, `segmentation`,
`funnel`, `retention`, `activity_feed`, `query_saved_report`, `list_bookmarks`,
`insights_query`, `query_saved_flows`, `frequency`, `segmentation_numeric`,
`segmentation_sum`, `segmentation_average`.

**C3 (38)**: `list_dashboards`, `create_dashboard`, `get_dashboard`, `update_dashboard`,
`delete_dashboard`, `bulk_delete_dashboards`, `favorite_dashboard`,
`unfavorite_dashboard`, `pin_dashboard`, `unpin_dashboard`,
`remove_report_from_dashboard`, `add_report_to_dashboard`, `list_blueprint_templates`,
`create_blueprint`, `get_blueprint_config`, `update_blueprint_cohorts`,
`finalize_blueprint`, `create_rca_dashboard`, `get_bookmark_dashboard_ids`,
`get_dashboard_erf`, `update_report_link`, `update_text_card`, `list_bookmarks_v2`,
`create_bookmark`, `get_bookmark`, `update_bookmark`, `delete_bookmark`,
`bulk_delete_bookmarks`, `bulk_update_bookmarks`, `bookmark_linked_dashboard_ids`,
`get_bookmark_history`, `list_cohorts_app`, `get_cohort`, `create_cohort`,
`update_cohort`, `delete_cohort`, `bulk_delete_cohorts`, `bulk_update_cohorts`.

**C4 (46)**: `list_feature_flags`, `create_feature_flag`, `get_feature_flag`,
`update_feature_flag`, `delete_feature_flag`, `archive_feature_flag`,
`restore_feature_flag`, `duplicate_feature_flag`, `set_flag_test_users`,
`get_flag_history`, `get_flag_limits`, `list_experiments`, `create_experiment`,
`get_experiment`, `update_experiment`, `delete_experiment`, `launch_experiment`,
`conclude_experiment`, `decide_experiment`, `archive_experiment`, `restore_experiment`,
`duplicate_experiment`, `list_erf_experiments`, `list_annotations`, `create_annotation`,
`get_annotation`, `update_annotation`, `delete_annotation`, `list_annotation_tags`,
`create_annotation_tag`, `list_webhooks`, `create_webhook`, `update_webhook`,
`delete_webhook`, `test_webhook`, `list_alerts`, `create_alert`, `get_alert`,
`update_alert`, `delete_alert`, `bulk_delete_alerts`, `get_alert_count`,
`get_alert_history`, `test_alert`, `get_alert_screenshot_url`,
`validate_alerts_for_bookmark`.

**C5 (64)**: `get_schemas`, `get_schema`, `list_schema_registry`, `create_schema`,
`create_schemas_bulk`, `update_schema`, `update_schemas_bulk`, `delete_schemas`,
`get_event_definitions`, `list_event_definitions`, `update_event_definition`,
`delete_event_definition`, `bulk_update_event_definitions`, `get_property_definitions`,
`list_property_definitions`, `update_property_definition`,
`bulk_update_property_definitions`, `list_lexicon_tags`, `create_lexicon_tag`,
`update_lexicon_tag`, `delete_lexicon_tag`, `get_tracking_metadata`, `get_event_history`,
`get_property_history`, `export_lexicon`, `list_drop_filters`, `create_drop_filter`,
`update_drop_filter`, `delete_drop_filter`, `get_drop_filter_limits`,
`list_custom_properties`, `create_custom_property`, `get_custom_property`,
`update_custom_property`, `delete_custom_property`, `validate_custom_property`,
`list_lookup_tables`, `get_lookup_upload_url`, `upload_to_signed_url`,
`register_lookup_table`, `mark_lookup_table_ready`, `get_lookup_upload_status`,
`update_lookup_table`, `delete_lookup_tables`, `download_lookup_table`,
`get_lookup_download_url`, `create_custom_event`, `update_custom_event`,
`delete_custom_event`, `get_schema_enforcement`, `init_schema_enforcement`,
`update_schema_enforcement`, `replace_schema_enforcement`, `delete_schema_enforcement`,
`run_audit`, `run_audit_events_only`, `list_data_volume_anomalies`, `update_anomaly`,
`bulk_update_anomalies`, `list_deletion_requests`, `create_deletion_request`,
`cancel_deletion_request`, `preview_deletion_filters`, `sign_replays`.

**C6 (0 api_client names)**: owns the `pagination.` prefix — the corpus carries exactly
one name, `pagination.paginate_all` (39 vectors).

### Index-absent Python surface (port anyway; zero vectors; document per R10.5)

These `MixpanelAPIClient` members carry NO api-index name and NO vectors, but the class
is incomplete (and B5/B6 consumers break) without them. Each ports in the shard that owns
its line range; locked by Layer-3 only:

| Member | Python lines | Shard | Consumer |
|---|---|---|---|
| `set_workspace_resolver` / `has_workspace_resolver` | `:352-387` | C1 | B6 `workspace.use` wiring; B8 MeService injection seam |
| `_get_auth_header` | `:388-416` | C1 | per-request auth (imports Phase-2 `sessionAuthHeader` path) |
| `_ensure_client` / `_http` | `:434-451`, `:1028-1035` | C1 | R6.2 connection reuse |
| properties `project_id`/`region`/`session`/`current_auth_header`/`workspace_id` | `:977-1035`, `:1390-1397` | C1 | everywhere |
| `with_project` | `:1696-1742` | C1 | B6 `workspace.use(project=…)` |
| `me` | `:1743-1770` | C1 | B8 MeService; B6 `workspace.me` |
| `_resolve_workspace_from_metadata` | `:1564-1636` | C1 | `resolve_workspace_id` fallback |
| `arb_funnels_query` | `:3082-3113` | C2 | B5 LiveQueryService (`query_funnel` path) |
| `list_custom_events` | `:8038-8067` | C5 | B6 W6b `list_custom_events` |
| `get_business_context` / `set_business_context` / `get_business_context_chain` | `:8681-8836` | C5 | B6 W1 business-context members |
| `_event_definitions` / `_property_definitions` (private shared cores) | `:6480-6514`, `:6669-6737` | C5 | its own lexicon methods (plain `app_request` GETs with `name[]` filters + bare-list shape validation — measured: they do NOT call `paginate_all`) |

**Packet measurement correction to the playbook**: P3-6's B4 row says the 183 include
`with_project` — measured against `corpus/api-index.json`, they do NOT (`with_project`
has no api-index entry and no vectors). The 183 DO include the four setup-only names
(`use`, `set_workspace_id`, `close`, `maybe_scoped_path`) plus `request`,
`resolve_workspace`, `resolve_workspace_id`, `require_scoped_path`. Scope is unchanged
(`with_project` still ports in C1, Layer-3-locked); only the name-list membership claim
is corrected. Second correction of the same kind: `api_client._iter_jsonl_lines` (6
vectors) is a corpus api name but NOT an api-index key — it is authored-registered
(`authored-apis.json`), B0-owned, already bound and `done`; the gate's 183-name diff must
run against the api-index keys, not the raw corpus name set.

### Expectation-shape measurement (all 843)

All 843 are `kind: "wire"`. **704 carry `expect.result`, 139 carry `expect.error`**
(subset-matched per `details_contain` — R5.2/R5.4: class/code/details, never message
text). **96 vectors carry `call.setup[]`** (112 setup entries among the 843; the
corpus-wide setup occurrence table below totals 134 because it also counts the 22
forward setups on workspace-measured vectors, P3-1 †); **all 843 carry
`call.session`; zero carry `call.workspace_session`**. Total recorded interactions:
**942** across 843 vectors (multi-interaction vectors = retry loops, pagination pages,
and setup-call traffic). Recorded streaming responses use `response.body_text`
(full-body; `createVectorFetch` rebuilds the stream) — `body_stream` chunked responses
exist only in B0's authored vectors. Chunk-boundary behavior is therefore locked by B0's
6 authored `jsonl-chunks` vectors + Layer-3, NOT by B4 replay: do not weaken the C2
Layer-3 chunk tests on the theory that vectors cover it.

**Setup-api universe and owners (all 15 `api_client.*` names + `workspace.me`)** — every
one must be bound before the vectors that carry it can replay; measured CORPUS-WIDE
occurrence counts (i.e. including the 22 forward setups on workspace-measured vectors):

| Setup api | Occurrences | Binding owner |
|---|---|---|
| `api_client.set_workspace_id` | 97 | C1 |
| `api_client.close` | 8 | C1 |
| `api_client.use` | 2 | C1 |
| `api_client.resolve_workspace` | 2 | C1 |
| `api_client.resolve_workspace_id` | 2 | C1 |
| `api_client.require_scoped_path` | 1 | C1 |
| `api_client.maybe_scoped_path` | 1 | C1 |
| `api_client.retention` | 4 | C2 |
| `api_client.list_bookmarks` | 4 | C2 |
| `api_client.get_property_values` | 3 | C2 |
| `api_client.get_events` | 3 | C2 |
| `api_client.get_event_properties` | 2 | C2 |
| `api_client.get_top_events` | 1 | C2 |
| `api_client.get_bookmark_dashboard_ids` | 2 | C3 |
| `api_client.get_schemas` | 1 | C5 |
| `workspace.me` | 1 | **B6** (the P3-1 † carried vector — stays UNPORTED at this gate; nobody in B4 binds it) |

Sequencing consequence: a vector whose setup api belongs to a not-yet-landed shard stays
UNPORTED (both prefixes pending until the gate flip) — never FAIL. C1's seven setup names
cover 113 of the 134 setup entries, which is why C1 is the hard prerequisite.

**Cross-shard setup scan (measured; determines per-shard interim PASS expectations)**:
among B4-measured vectors, the ONLY cross-shard setup dependency is on C1 — 53 C2-measured,
23 C4-measured, 1 C3-measured, and 2 C5-measured vectors carry C1-owned setups
(`set_workspace_id`/`close`/…), plus the 1 C1-measured carried vector whose setup is
`workspace.me` (B6). No B4-measured vector depends on a C2/C3/C4/C5/C6 setup from another
shard. Therefore, with C1 landed first, each later shard's FULL vector count passes as it
lands, independent of sibling order. Per-shard interim PASS deltas: C1 **+80** (81 − the
carried vector), C2 **+317**, C3 **+78**, C4 **+109**, C5 **+219**, C6 **+39**; cumulative
sum = **842** = the gate delta. (The interim PASS totals quoted in the per-shard
done-criteria assume the C1→C2→…→C6 landing order for illustration; under parallel
landing the deltas hold and the totals reorder.)

### Corpus location (all 843 + the 6 B0-owned, by file)

`conformance-runner/corpus/…`; counts include every `api_client.*`/`pagination.*`
measured vector in the file (the 6 in `authored/streaming/jsonl-chunks.jsonl` are
B0-owned `_iter_jsonl_lines`, listed for completeness — sum below = 849):

| file | n | | file | n |
|---|---|---|---|---|
| `entities/test_api_client_data_governance.jsonl` | 64 | | `bookmarks/test_api_client.jsonl` | 11 |
| `discovery/test_api_client.jsonl` | 42 | | `bookmarks/test_api_client_phase008.jsonl` | 11 |
| `entities/test_api_client_governance.jsonl` | 41 | | `bookmarks/test_api_client_crud_edge.jsonl` | 11 |
| `discovery/test_discovery.jsonl` | 41 | | `bookmarks/test_api_client_bookmarks.jsonl` | 11 |
| `data-governance/test_api_client_data_governance.jsonl` | 40 | | `replays/test_api_client_sign_replays.jsonl` | 10 |
| `pagination/test_pagination.jsonl` | 39 | | `cohorts/test_api_client_crud.jsonl` | 10 |
| `entities/test_api_client_schemas.jsonl` | 39 | | `entities/test_schema_graph.jsonl` | 8 |
| `engage/test_api_client_engage_stats.jsonl` | 37 | | `discovery/test_live_query.jsonl` | 7 |
| `engage/test_api_client.jsonl` | 34 | | `segmentation/test_live_query.jsonl` | 6 |
| `entities/test_app_api_client.jsonl` | 29 | | `retention/test_live_query.jsonl` | 6 |
| `entities/test_api_client_alerts.jsonl` | 26 | | `funnels/test_live_query.jsonl` | 6 |
| `entities/test_api_client_experiments.jsonl` | 25 | | `authored/streaming/jsonl-chunks.jsonl` | 6 (B0) |
| `entities/test_api_client_crud.jsonl` | 25 | | `streaming/test_api_client_data_governance.jsonl` | 5 |
| `entities/test_api_client_flags.jsonl` | 23 | | `retention/test_live_query_phase008.jsonl` | 5 |
| `entities/test_api_client.jsonl` | 21 | | `retention/test_api_client_phase008.jsonl` | 5 |
| `entities/test_api_client_annotations.jsonl` | 20 | | `entities/test_live_query.jsonl` | 5 |
| `entities/test_api_client_crud_edge.jsonl` | 18 | | `discovery/test_query_workspace_scoping.jsonl` | 5 |
| `auth/test_workspace_resolution.jsonl` | 16 | | `cohorts/test_discovery.jsonl` | 5 |
| `segmentation/test_api_client_phase008.jsonl` | 15 | | `segmentation/test_api_client.jsonl` | 4 |
| `bookmarks/test_live_query_phase008.jsonl` | 14 | | `retention/test_api_client.jsonl` | 4 |
| `bookmarks/test_api_client_crud.jsonl` | 14 | | `funnels/test_discovery.jsonl` | 4 |
| `entities/test_api_client_webhooks.jsonl` | 13 | | `cohorts/test_api_client_crud_edge.jsonl` | 4 |
| `streaming/test_api_client.jsonl` | 12 | | `entities/test_workspace_resolution.jsonl` | 3 |
| `segmentation/test_live_query_phase008.jsonl` | 12 | | `entities/test_workspace_lazy_resolve.jsonl` | 2 |
| `entities/test_lexicon_schemas.jsonl` | 12 | | `entities/test_settings_headers.jsonl` | 2 |
| `funnels/test_api_client_bookmarks.jsonl` | 11 | | `bookmarks/test_api_client_alerts.jsonl` | 2 |
| | | | `auth/test_app_api_client.jsonl` | 2 |
| | | | 6 files with 1 each (`streaming/test_query_workspace_scoping`, `retention/test_api_client_bookmarks`, `funnels/test_api_client`, `entities/test_query_workspace_scoping`, `entities/test_api_client_session`, `bookmarks/test_query_workspace_scoping`) | 6 |

**Replay-filter trap (substring matching)**: vector ids embed the api name as a path
segment; `npm run conformance -- --filter <substring>` is a SUBSTRING match. Several B4
names prefix each other — `api_client.list_bookmarks` also matches `list_bookmarks_v2`
(different shards!), `list_cohorts` matches `list_cohorts_app`, `get_schema` matches
`get_schemas`/`get_schema_enforcement`, `run_audit` matches `run_audit_events_only`,
`export_profiles` matches `export_profiles_page`, `create_annotation` matches
`create_annotation_tag`, `update_schema` matches `update_schemas_bulk`/
`update_schema_enforcement`. Per-name replay MUST use the trailing-slash form
(`--filter "api_client.list_bookmarks/"`); per-shard replay = iterate the shard's name
list with trailing slashes.

---

## Wire enablement (P3-5 §1–§3, instantiated for B4) — lands with C1

**`clientFromSession(context)` — ONE shared helper in the rig** (fable rig code; B4 is
all-fable so it lands inline in the C1 task's binding commit, P3-2 b′). Spec, binding on
every B4 binding:

1. Reads `context.session` (the raw D5 canonical fake session — e.g. `{account_name,
   project_id, region, token, type: "oauth_token"}`; present on ALL 843 vectors, measured)
   → `parseAccount(...)` (Phase-2 C4 factory, `packages/core/src/auth/account.ts`) →
   `Session` → `createMixpanelClient({session, fetch, sleep, random, now})`.
   Auth headers are built by the REAL Phase-2 auth model
   (`accountAuthHeader`/`sessionAuthHeader`) and diffed byte-exactly against recorded
   headers; the canonicalizer's auth-header pattern matching stays as backstop.
2. **MEMOIZES the constructed client in `context.state`** under ONE well-known key
   (fix the spelling in code, e.g. `"api_client"`), so `call.setup[]` entries and the
   measured call operate on the SAME instance (`runner.ts` creates one `state` map + one
   `createVectorFetch` harness per vector and runs setup entries through the bindings
   BEFORE the measured call — `runner.ts:446`/`:450`, `:478-505`). A fresh client per
   invocation would let the 97 `set_workspace_id` setups (+ `close` 8, `retention` 4,
   `list_bookmarks` 4, `use` 2, `resolve_workspace` 2, `resolve_workspace_id` 2, and the
   other discovery prerequisites) mutate a throwaway object — every workspace-scoped
   vector would FAIL_REQUEST with a project-scoped path.
3. **Determinism seams injected by every wire binding** (P3-5 §2):
   `fetch: context.fetch` (the `createVectorFetch` harness — `requireFetch(context)`,
   `bindings.ts:188-195`), `sleep: () => Promise.resolve()` (zero-delay),
   `random: () => 0` (kills backoff jitter variance — legal: sleep durations are not
   vector-observable, only request sequences are), `now: () => recordEpoch`
   (`context.shims`, D1.4 clock freeze). Timing-sensitive behavior is Layer-3's job
   (Vitest fake timers), never Layer-2's.
4. **Binding honesty (P3-5 §3, arbiter-checked per shard)**: a binding calls the ported
   client method by name (`api_client.X` → `client.X(...)` — the same public entry point
   the recorder wrapped) and NOTHING else. Bindings never assemble requests, never
   re-derive paths/params, never bypass `createMixpanelClient`. Risk-register #2
   (ScanCode failure mode) names this the top B4 risk; the arbiter verifies binding
   honesty for EVERY shard.
5. **AbortSignal (R6.7 + the B0-ARB carried item 6a, `B0-notes.md` arbiter addendum)**:
   R6.7's four points (between pages, into the request, into the backoff sleep,
   normalized on exit — every cancellation throws `DOMException(…, 'AbortError')`) are
   satisfied via **signal-aware `request`/`sleep` closures built at client assembly,
   WITHOUT touching the B0 module signatures**: `createMixpanelClient` (and C6's
   paginator) accepts `signal?: AbortSignal` per call, curries it into the `fetch`
   adapter call (`fetch(url, {signal, redirect: 'manual', …})`) and into a
   signal-racing sleep wrapper around the injected `sleep`. B0's `executeWithRetry`/
   `appRequest`/`backoff` are imported as-is. The gate verifies this carried item lands.

**Binding plan (the b′ rule for an all-fable batch)**: there is NO separate binding task.
Each shard task (C1–C6) lands its own api-name registrations in
`conformance-runner/src/bindings.ts`'s registration modules **inline, in the same commit
as the module code** (P3-2 b′ fable-batch rule), runs its own vectors to green while the
prefixes are still `pending` (bound names replay immediately; P3-5 §4 B4 note), and then
runs its R10.9 harness (P3-2 c). The SHARED b-prime work — `clientFromSession`, the
`context.state` memoization key, the determinism-seam plumbing — lands ONCE with C1;
C2–C6 import it, never fork it. Oracle registration: wire api names have NO oracle
`call` surface (P3-2 c / P3-2 e item 3 — they are exempt from the both-bridge probe);
nothing to register beyond the bindings.

**Batch-status flip spec (P3-5 §4, executes at the GATE, not per shard)**: one flip, in
the same commit as the gate checkpoint: `api_client.` → `done` AND `pagination.` →
`done`. Notes:
- The existing exact-name entry `api_client._iter_jsonl_lines` → `done` (landed at B0)
  becomes shadowed-but-consistent under longest-prefix matching
  (`batch-status.ts:90-95`); keep it (harmless) or fold it — either way the
  prefix-coverage unit test must stay green.
- Run the STANDING collision assertion after editing: mechanically scan all corpus api
  names for `startsWith` hits against the new entries requiring a longer `pending`
  override. Expected result at this pin: none for B4 (`api_client.`/`pagination.`
  capture only B4/B0-owned names; `workspace.*` is untouched). Record the scan in the
  gate notes.
- **Forward note for the B5 packet author (P3-5 §4, do NOT act on it at B4)**: the B5
  gate's generated exact-name entry `workspace.list_bookmarks` (B5 member, zero vectors)
  prefix-captures the B6 member `workspace.list_bookmarks_v2` (7 vectors) — B5 must add
  the longer override `workspace.list_bookmarks_v2` → `pending` or those 7 UNPORTED B6
  vectors flip to FAIL_ERROR. B4's gate notes must carry this forward.
- UNPORTED must drop by exactly **842** (not 843): the carried
  `auth/api_client.resolve_workspace_id/test_workspace_resolution-testfacaderesolverwiring-…`
  vector keeps its `workspace.me` setup gated on the pending `workspace.` prefix. The 22
  forward setups (workspace-measured vectors with `api_client.*` setups) stay UNPORTED
  on their own measured-api pendency — benign, by design (P3-5 §5).

**Wire R10.9 harness rule (P3-2 c, applies to every shard)**: wire methods have no oracle
bridge surface, so the harness = the mandatory edge set replayed through
`createVectorFetch` with HAND-BUILT interactions covering **every `_handle_response`
status branch reachable from the shard's methods** (200-object, 200-array, 200-scalar,
200-non-JSON, 3xx, 400, 401, 403-plain, 403-sensitive-data + the R10.7 bug-compat matrix
where applicable, 404, other-4xx, 422-app, 429-retry-then-success, 429-exhausted, 5xx,
204-app, network-error/transport_error rejection) plus the fixed edge values (`18.0`,
`1.5`, `True`, `None`, `[]`, `""`, `"𝒳"`) flowing through params/body encoding. Harness
lives in `throwaway/b4-cX/` inside the shard commit; RUN record (counts, branch table)
appended to the shard notes; review pair re-runs it (P3-2 d item 5); the GATE removes
`throwaway/` after arbiter sign-off.

---

## Packet C1 — client core + wire-enablement seam (FIRST; everything depends on it)

**Model**: fable, ≤ high. **Vectors: 81** (11 names; 4 setup-only at zero). Notes file:
`context/phase3/notes/B4-C1-notes.md`.

### Python sources (re-read every range; lines at support-branch HEAD)

`src/mixpanel_headless/_internal/api_client.py`:
- Module head/constants/types: `:1-286` (imports, `WorkspaceResolver` import, module
  docstring; `_error_message`/`_iter_jsonl_lines`/`ENDPOINTS` in `:81-172` are B0 —
  IMPORT, never re-implement).
- `class MixpanelAPIClient` `:287-305`; `__init__` `:306-351` (default
  `max_retries = 3` at `:312`); `set_workspace_resolver`/`has_workspace_resolver`
  `:352-387`; `_get_auth_header` `:388-416`; `_ensure_client` `:434-451`; `close` +
  context manager `:483-502`; `_request` `:822-920`; public `request` `:921-976`
  (escape hatch, 15 vectors); properties `:977-1035`; `use` `:1036-1113`;
  `resolve_workspace` `:1114-1158`; `workspace_id`/`set_workspace_id` `:1390-1426`;
  `resolve_workspace_id` `:1427-1527`; `projects_metadata_index` `:1528-1563`;
  `_resolve_workspace_from_metadata` `:1564-1636`; `require_scoped_path` `:1666-1695`;
  `with_project` `:1696-1742`; `me` `:1743-1770`; `list_workspaces` `:1771-1812`.
- B0-owned, C1 imports by name (R10.8; risk-register #1 grep target): `_build_url` →
  `client/url.ts` `buildUrl`/`endpointBase`; `_request_headers` → `client/headers.ts`
  `requestHeaders` (4-layer merge — do NOT re-merge); `_handle_response`/
  `_execute_with_retry`/`_error_message` → `client/internals.ts`; backoff trio →
  `client/backoff.ts`; `app_request` → `client/app-request.ts` `appRequest`;
  `maybe_scoped_path` → `client/scope.ts`; `parseLossless` → `client/lossless-json.ts`;
  `QUERY_ORIGIN`/`getUserAgent` → `client/headers.ts` (client_metadata.py already ported
  at B0).

`src/mixpanel_headless/_internal/me.py` — **pure selection half ONLY** (playbook
Discrepancy #5): models `MeOrgInfo` `:40-72`, `MeProjectInfo` `:73-116`,
`MeWorkspaceInfo` `:117-170`, `MeResponse` `:171-233`, `WorkspaceView` `:234-338`,
`select_workspace_id` `:339-384`, `WorkspaceResolver` protocol `:385-411`. `MeCache`
`:413-608` and `MeService` `:609-915` are **B8-N2** — do not port, do not stub beyond
the `WorkspaceResolver` interface C1 consumes.

### TS home

`packages/core/src/client/client.ts` — `createMixpanelClient(options)` factory (R2.9:
factory over injectable transport; R2.4 `fetch?: typeof fetch`; injectable
`sleep`/`random`/`now`; per-call `signal?: AbortSignal` per §Wire-enablement item 5).
The factory assembles the domain methods: C1 ships the core methods + the assembly
spread points; C2–C5 each add one `...create<Domain>Methods(core)` spread (documented
merge point — append-only). `packages/core/src/client/me.ts` — me-selection logic
(models as plain validated shapes, `WorkspaceView`, `selectWorkspaceId`,
`WorkspaceResolver` interface). R2.13: every URL by string concatenation. R2.11:
`redirect: 'manual'` in the fetch adapter + throwing raise_for_status analog (B0
`internals.ts`). R2.12: ms at the sleep seam only; `*Seconds` names for Python-seconds
values in any serialized detail.

### Behavior spine (byte-for-byte; each line = a review-pair assertion)

- `request()` `:921-976`: validates api_type ∈ {query, app, data}; delegates to
  `_request` which routes query/data hosts through `_execute_with_retry` and app through
  `app_request` — re-read the source for the exact routing and param threading
  (`request_params` threading is post-PR-206 behavior, locked by
  `test_api_client.py:4085-4095` asserts).
- `use()` `:1036-1113`: rebuilds the auth header but REUSES the underlying HTTP client
  (R6.2 — same instance; `TestTransportPreservation`,
  `test_api_client_session.py:97`); clears stale workspace pins
  (`TestUseClearsStaleWorkspaceId` `:124`); OAuth atomicity (`TestUseOAuthAtomicity`
  `:166`).
- `resolve_workspace_id()` `:1427-1527`: resolver-first (injected `WorkspaceResolver`),
  then `projects_metadata_index` fallback (`_resolve_workspace_from_metadata`
  `:1564-1636` + `select_workspace_id` from me.ts), raising `WorkspaceScopeError` per
  source; memoizes into `workspace_id`. The 14 vectors + 2 setup occurrences replay
  the fallback wire traffic; the resolver-injected path is Layer-3
  (`TestResolveWorkspaceIdWithResolver`).
- `require_scoped_path` `:1666-1695` raises where `maybe_scoped_path` falls back —
  port the exact error class/code.
- `me()` `:1743-1770` + `list_workspaces()` `:1771-1812`: plain wire calls (App API);
  `list_workspaces` maps to `PublicWorkspace` (Phase-2 type).

### Layer-3 translation scope (C1)

| Source | Classes |
|---|---|
| `tests/unit/test_api_client_session.py` (368) | ALL (TestConstruction :56, TestUse :71, TestTransportPreservation :97, TestUseClearsStaleWorkspaceId :124, TestUseOAuthAtomicity :166, TestSessionAccountNameDrivesMeCacheScope :231, TestAppRequestUsesFreshAuthHeader :269) |
| `tests/unit/test_api_client.py` (4,259) | The construction/close/context-manager and TestPublicRequest (:1578+) classes; the retry/backoff/handler classes were translated at B0 — file-header exclusion citing `b0-review-assertions.md`; C2 takes the streaming/export/query classes |
| `tests/unit/test_query_workspace_scoping.py` (435) | Client-side classes: TestQueryHostInjectionWhenPinned :128, TestInjectionOptOut :191, TestNoWorkspacePinned :224, TestNonQueryHostsUnaffected :273, TestPinLifecycle :324. TestWorkspaceFacadeScoping :379 + TestDiscoveryCacheAcrossUse :401 are facade/service tests → B5/B6 (header exclusion citing this packet) |
| `tests/unit/test_workspace_resolution.py` (791) | TestSelectWorkspaceId :96, TestResolveWorkspaceIdWithResolver :228, TestProjectsMetadataIndex :459. TestMeServiceResolveWorkspace :154 → B8; TestFacadeResolverWiring :611 → B6 (header exclusions citing this packet + playbook Discrepancy #5) |
| `tests/pbt/test_workspace_resolution_pbt.py` | select_workspace_id precedence PBT → fast-check, same strategy shapes |
| `tests/unit/test_me.py` (pure half) | TestMeOrgInfo :38, TestMeProjectInfo :71, TestMeWorkspaceInfo :108, TestMeResponse :149. TestMeCache*/TestMeService/symlink classes → B8 (header exclusion) |
| `tests/unit/test_api_client_pbt.py` (705) | TestAuthHeaderProperties :98 (C1). TestBackoffProperties :206, TestUrlBuildProperties :336, TestIterJsonlLinesProperties :537 lock B0-owned modules but were NOT translated at B0 (verified: no fast-check in `packages/core/test/client/`) — translate them HERE against the B0 modules. TestActivityFeedDateRange :673 → C2 |
| `tests/unit/test_app_api_client.py` (929) | B0 deferrals only: `test_form_body_sent_as_form_encoded` :316 content-type assertion (adapter-owned) + the auth-header wire-capture tests (Bearer/Basic recorded end-to-end — now real via clientFromSession). The rest was translated at B0 (header exclusion citing `B0-notes.md` deviation-3) |

### R10.10 consumers (api-map rows pasted; C1)

The three B4 api-map members (verbatim rows; `stream_*` are C2 deliverables but consume
C1's client object; `api` is the escape hatch B6 exposes over the C1 factory):

```json
{"name":"stream_events","kind":"method","public":true,"section":"STREAMING METHODS","params":[],"kwonly":["from_date","to_date","events","where","limit","raw"],"returns":"Iterator[dict[str, Any]]","iterator":true,"lineno":1381,"batch":"B4","package":"core","ts_signature":"stream_events(from_date, to_date, events, …): AsyncIterable<dict[str, Any]>"}
{"name":"stream_profiles","kind":"method","public":true,"section":"STREAMING METHODS","params":[],"kwonly":["where","cohort_id","output_properties","raw","distinct_id","distinct_ids","group_id","behaviors","as_of_timestamp","include_all_users"],"returns":"Iterator[dict[str, Any]]","iterator":true,"lineno":1450,"batch":"B4","package":"core","ts_signature":"stream_profiles(where, cohort_id, output_properties, …): AsyncIterable<dict[str, Any]>"}
{"name":"api","kind":"property","public":true,"section":"ESCAPE HATCHES","params":[],"kwonly":[],"returns":"MixpanelAPIClient","iterator":false,"lineno":4446,"batch":"B4","package":"core","ts_signature":"get api(): MixpanelAPIClient"}
```

B6 facade members that are name-matched delegates of C1 methods (condensed api-map rows):

```json
{"name":"use","batch":"B6","params":[],"kwonly":["account","project","workspace","target","persist"],"returns":"Workspace","ts_signature":"async use(account, project, workspace, …): Promise<Workspace>"}
{"name":"close","batch":"B6","params":[],"kwonly":[],"returns":"None","ts_signature":"async close(): Promise<void>"}
{"name":"list_workspaces","batch":"B6","params":[],"kwonly":[],"returns":"list[PublicWorkspace]","ts_signature":"async list_workspaces(): Promise<list[PublicWorkspace]>"}
{"name":"resolve_workspace_id","batch":"B6","params":[],"kwonly":[],"returns":"int","ts_signature":"async resolve_workspace_id(): Promise<number>"}
```

Plus: every C2–C6 method (internal consumer of the factory core); B7
`Workspace.use`-adjacent resolver wiring; B8 MeService implements the
`WorkspaceResolver` interface defined here.

### R10.9 harness spec (C1) — `throwaway/b4-c1/`

Status-branch replay through hand-built VectorFetch interactions on `request()` (query +
app + data routes) and `resolve_workspace_id()` (metadata fallback): the full §Wire rule
branch list, PLUS: `use()` preserving the fetch/transport identity (R6.2 — assert same
harness continues serving), workspace pin set→cleared across `use`, scalar-return 200
(`42`/`"ok"`/`true`/`null` — returned, not raised), `INVALID_RESPONSE` on non-JSON 200,
3xx-with-JSON-body → `HTTP_ERROR` (never success; R2.11), 429-exhausted carrying
`project_id` (FF4), edge values through `request(params=…)` encoding. RUN record to the
notes file.

### Done-criteria (C1)

Files on disk; `tsc --strict` clean; `npm run check` green; translated tests green; ALL
81 C1 vectors PASS (+ the 96 setup-carrying vectors across other shards begin replaying
as their measured shards land — C1 itself must leave the 4 setup-only bindings working:
verified by any C2+ vector with a `set_workspace_id` setup once C2 lands, and at C1 time
by the bindings unit path + the 2 `entities/test_workspace_lazy_resolve.jsonl` vectors);
`clientFromSession` + memoization landed in `bindings.ts`; R10.9 RUN record written; one
TS commit (+ the notes-file commit on the Python support branch). Conformance interim
expectation after C1 alone: 1,528 + **80** = **1,608 PASS / 0 FAIL** (81 minus the P3-1 †
carried vector, which stays UNPORTED on its `workspace.me` setup; prefixes still pending —
no flip).

---

## Packet C2 — Query-host methods + streaming/export (volume center: 317 vectors)

**Model**: fable, ≤ high. **Vectors: 317** (24 names; heaviest: `get_events` 54,
`export_profiles_page` 31, `activity_feed` 26, `get_property_values` 23, `engage_stats`
21, `query_saved_report` 20, `export_profiles` 19, `export_events` 13). 53 of the 317
carry C1-owned setups — C2 requires C1 landed. Notes:
`context/phase3/notes/B4-C2-notes.md`.

### Python sources

`api_client.py:1813-3293`, in source order: `export_events` `:1813-1953` (streaming
generator; per-line `json.loads` at `:1931`; its own inline 429 loop with the
RateLimitError raise at `:1883-1891`; 429 body parse `json.loads(body)` `:1911`),
`export_profiles` `:1954-2110` (paged generator), `export_profiles_page` `:2111-2250`,
`engage_stats` `:2251-2356`, `get_events` `:2357-2429`, `get_event_properties`
`:2430-2449`, `get_property_values` `:2450-2481`, `list_funnels` `:2482-2497`,
`list_cohorts` `:2498-2516`, `get_top_events` `:2517-2546`, `event_counts` `:2547-2586`,
`property_counts` `:2587-2641`, `segmentation` `:2642-2686`, `funnel` `:2687-2737`,
`retention` `:2738-2799`, `activity_feed` `:2800-2910`, `query_saved_report`
`:2911-2989`, `list_bookmarks` `:2990-3021` (LEGACY query-side listing — the App-API
twin `list_bookmarks_v2` is C3), `insights_query` `:3022-3053`, `query_saved_flows`
`:3054-3081`, `arb_funnels_query` `:3082-3113` (index-absent, port anyway),
`frequency` `:3114-3163`, `segmentation_numeric` `:3164-3207`, `segmentation_sum`
`:3208-3248`, `segmentation_average` `:3249-3293`.

### TS homes

`packages/core/src/services/queries/` per R7.2 — suggested split:
`query-host.ts` (segmentation family, funnel, retention, frequency, activity feed,
top events, event/property counts, insights/saved-report/saved-flows/arb-funnels,
legacy list_bookmarks, get_events/get_event_properties/get_property_values,
list_funnels/list_cohorts), `engage.ts` (engage_stats, export_profiles_page),
`streaming.ts` (export_events, export_profiles — `async function*` over
`iterJsonlLines` from B0 `client/jsonl.ts`, R2.6/R3.2). Each exports a
`create<X>Methods(core)` factory spread into `createMixpanelClient` (one appended line
in `client/client.ts`). The **3 B4 api-map members** land here: `stream_events`/
`stream_profiles` (facade-level thin wrappers over export_events/export_profiles —
api-map rows pasted in the C1 packet; `workspace.py:1381-1449` `stream_events` calls
`api_client.export_events` at `:1455`, `stream_profiles` calls `export_profiles` at
`:1561`) and the `api` property (B6 exposes it; nothing to build beyond the factory).

### Behavior spine (byte-for-byte)

- **Streaming (R2.6/R3.2/R6.6)**: `export_events` iterates `_iter_jsonl_lines` (B0
  `iterJsonlLines` — import by name) over the raw-endpoint response; parses each line
  with `parseLossless(line, { pythonConstants: true })` (Python `json.loads` at `:1931`
  accepts `NaN`/`Infinity`/`-Infinity` — GATE-R5 + B0 arbiter F1; same for the 429 body
  parse at `:1911`); `raw=True` yields undecoded lines — port the exact branch.
  Item-level `yield*` (R6.6). AbortSignal at all four R6.7 points via the C1 closures.
- **The streaming RateLimitError raise `:1883-1891` (B0 deviation-3 deferral — MUST land
  here)**: its constructor shape omits `response_body` ONLY (carries `retry_after`,
  `status_code`, `request_method="GET"`, `request_url`, `request_params`,
  `project_id=self.project_id`). Layer-3 lock: `test_api_client.py:1560-1575`
  (`exc_info.value.project_id == "12345"` after `list(client.export_events(...))`).
  Also port `test_export_events_negative_retry_after_uses_backoff`
  (`test_api_client.py:3810`) — negative Retry-After falls back to jittered backoff.
- **`export_profiles`/`export_profiles_page`**: paged engage exports; `page`/
  `session_id` threading, `total`/page-size termination — re-read `:1954-2250` and port
  the loop conditions exactly (off-by-one here is vector-visible in request sequences).
- **Query-host methods**: all delegate to `_execute_with_retry` (B0) with
  `params.query_origin = QUERY_ORIGIN` injected there — bindings and methods NEVER add
  it themselves (double-injection is vector-visible). Workspace pinning: when
  `workspace_id` is set, query-host params gain the workspace scope per
  `test_query_workspace_scoping.py` semantics (C1 owns the pin; C2 methods must not
  bypass it).
- **Result plumbing**: methods return the parsed body verbatim (dict/list passthrough
  from `_handle_response`); the RESULT-shaping into `SegmentationResult` etc. is B5
  (LiveQueryService) — do NOT pre-shape here (C8-deferral boundary).

### Layer-3 translation scope (C2)

| Source | Scope |
|---|---|
| `tests/unit/test_api_client.py` | Streaming/export/query classes: TestRetryStateResetRegression :1401-… (**4 tests — B0 deviation-3 deferral, lands HERE**: batch-count/callback state resets across retry attempts in export flows), the export_events/export_profiles suites (incl. :1560-1575 project_id lock), get_events/query-method suites, :3810 negative-retry-after. B0-translated handler/backoff classes: header exclusion citing `b0-review-assertions.md` |
| `tests/test_api_client_engage_stats.py` (820) | ALL — engage_stats + export_profiles_page params/paging/error mapping |
| `tests/unit/test_api_client_phase008.py` (764) | ALL (TestActivityFeed :49, TestSegmentationSum :128, TestSegmentationAverage :182, TestFrequency :236, TestSegmentationNumeric :290, TestQuerySavedReport :347, TestPhase008ErrorHandling :398) |
| `tests/unit/test_api_client_pbt.py` | TestActivityFeedDateRange :673 → fast-check |
| Dedicated async Layer-3 (plan §7 / playbook B4 row) | NEW Vitest suites with fake timers + delayed mock responses: streaming chunk behavior across await points, retry timing in the export 429 loop, AsyncIterable early-`return()` (abort between yields) |

### R10.10 consumers (api-map rows pasted; C2)

B5 members (LiveQueryService/DiscoveryService delegate name-map measured from
`services/live_query.py` + `services/discovery.py`):

```json
{"name":"segmentation","batch":"B5","params":["event"],"kwonly":["from_date","to_date","on","unit","where"],"returns":"SegmentationResult","ts_signature":"async segmentation(event, from_date, to_date, …): Promise<SegmentationResult>"}
{"name":"funnel","batch":"B5","params":["funnel_id"],"kwonly":["from_date","to_date","unit","on"],"returns":"FunnelResult","ts_signature":"async funnel(funnel_id, from_date, to_date, …): Promise<FunnelResult>"}
{"name":"retention","batch":"B5","params":[],"kwonly":["born_event","return_event","from_date","to_date","born_where","return_where","interval","interval_count","unit"],"returns":"RetentionResult","ts_signature":"async retention(born_event, return_event, from_date, …): Promise<RetentionResult>"}
{"name":"event_counts","batch":"B5","params":["events"],"kwonly":["from_date","to_date","type","unit"],"returns":"EventCountsResult","ts_signature":"async event_counts(events, from_date, to_date, …): Promise<EventCountsResult>"}
{"name":"property_counts","batch":"B5","params":["event","property_name"],"kwonly":["from_date","to_date","type","unit","values","limit"],"returns":"PropertyCountsResult","ts_signature":"async property_counts(event, property_name, from_date, …): Promise<PropertyCountsResult>"}
{"name":"activity_feed","batch":"B5","params":["distinct_ids"],"kwonly":["from_date","to_date","limit","include_events","exclude_events","sentinel_event","paging_window","search","search_properties","use_custom_events"],"returns":"ActivityFeedResult","ts_signature":"async activity_feed(distinct_ids, from_date, to_date, …): Promise<ActivityFeedResult>"}
{"name":"query_saved_report","batch":"B5","params":["bookmark_id"],"kwonly":["bookmark_type","from_date","to_date"],"returns":"SavedReportResult","ts_signature":"async query_saved_report(bookmark_id, bookmark_type, from_date, …): Promise<SavedReportResult>"}
{"name":"query_saved_flows","batch":"B5","params":["bookmark_id"],"kwonly":[],"returns":"FlowsResult","ts_signature":"async query_saved_flows(bookmark_id): Promise<FlowsResult>"}
{"name":"frequency","batch":"B5","params":[],"kwonly":["from_date","to_date","unit","addiction_unit","event","where"],"returns":"FrequencyResult","ts_signature":"async frequency(from_date, to_date, unit, …): Promise<FrequencyResult>"}
{"name":"segmentation_numeric","batch":"B5","params":["event"],"kwonly":["from_date","to_date","on","unit","where","type"],"returns":"NumericBucketResult","ts_signature":"async segmentation_numeric(event, from_date, to_date, …): Promise<NumericBucketResult>"}
{"name":"segmentation_sum","batch":"B5","params":["event"],"kwonly":["from_date","to_date","on","unit","where"],"returns":"NumericSumResult","ts_signature":"async segmentation_sum(event, from_date, to_date, …): Promise<NumericSumResult>"}
{"name":"segmentation_average","batch":"B5","params":["event"],"kwonly":["from_date","to_date","on","unit","where"],"returns":"NumericAverageResult","ts_signature":"async segmentation_average(event, from_date, to_date, …): Promise<NumericAverageResult>"}
{"name":"list_bookmarks","batch":"B5","params":["bookmark_type"],"kwonly":[],"returns":"list[BookmarkInfo]","ts_signature":"async list_bookmarks(bookmark_type): Promise<list[BookmarkInfo]>"}
{"name":"query_user","batch":"B5","params":[],"kwonly":["where","cohort","properties","sort_by","sort_order","limit","search","distinct_id","distinct_ids","group_id","as_of","mode","aggregate","aggregate_property","percentile","segment_by","parallel","workers","include_all_users"],"returns":"UserQueryResult","ts_signature":"async query_user(where, cohort, properties, …): Promise<UserQueryResult>"}
```

Delegate map for the no-facade-twin names (measured): DiscoveryService —
`list_events→get_events`, `list_properties→get_event_properties`,
`list_property_values→get_property_values`, `list_top_events→get_top_events`,
`list_funnels→list_funnels`, `list_cohorts→list_cohorts`,
`list_bookmarks→list_bookmarks` (B5-S1); LiveQueryService — `insights_query`,
`arb_funnels_query`, plus the twelve name-matched members above (B5-S2);
`workspace.query_user` internals consume `export_profiles_page` + `engage_stats`
(`workspace.py:9685`, `:9700`, `:10048`, `:10110`, `:10155` — B5-S2);
`workspace.stream_events`/`stream_profiles` (B4, this shard) consume
`export_events`/`export_profiles`.

### R10.9 harness spec (C2) — `throwaway/b4-c2/`

§Wire rule branch list through `segmentation` (query-host representative) AND
`export_events` (streaming representative: 429-then-success mid-export, exhausted-429
with the `:1883-1891` reduced shape, malformed JSONL line → parse error, empty-body
stream, non-BMP `"𝒳"` inside event JSON, `pythonConstants` line `NaN`), plus
`export_profiles_page` paging termination and `engage_stats` param encoding with the
fixed edge values. Every error branch of the shard's registry codes enumerated.

### Done-criteria (C2)

`tsc --strict` clean; `npm run check` green; translated tests green; all 317 vectors
PASS (C1 prerequisite landed); TestRetryStateResetRegression ×4 + :3810 +
:1560-1575 locks present (gate verifies the B0-ARB carried item 6b); R10.9 RUN record;
commits per repo. Interim conformance after C1+C2: **1,925 PASS / 0 FAIL**.

---

## Packet C3 — entity CRUD: dashboards + bookmarks(v2) + cohorts (78 vectors)

**Model**: fable, ≤ high. **Vectors: 78** (38 names). 1 vector carries a C1 setup.
Notes: `context/phase3/notes/B4-C3-notes.md`.

### Python sources

`api_client.py:3650-4937`, in source order: dashboards `:3650-4046` (`list_dashboards`
`:3650`, `create_dashboard` `:3689`, `get_dashboard` `:3724`, `update_dashboard`
`:3759`, `delete_dashboard` `:3797`, `bulk_delete_dashboards` `:3824`,
`favorite_dashboard` `:3851`, `unfavorite_dashboard` `:3878`, `pin_dashboard` `:3905`,
`unpin_dashboard` `:3932`, `remove_report_from_dashboard` `:3959`,
`add_report_to_dashboard` `:4003`); blueprints/RCA `:4047-4283`
(`list_blueprint_templates` `:4047`, `create_blueprint` `:4107`, `get_blueprint_config`
`:4145`, `update_blueprint_cohorts` `:4180`, `finalize_blueprint` `:4210`,
`create_rca_dashboard` `:4245`); dashboard-adjacent `:4284-4426`
(`get_bookmark_dashboard_ids` `:4284`, `get_dashboard_erf` `:4320`,
`update_report_link` `:4355`, `update_text_card` `:4389`); bookmarks v2 `:4427-4735`
(`list_bookmarks_v2` `:4427`, `create_bookmark` `:4479`, `get_bookmark` `:4515`,
`update_bookmark` `:4545`, `delete_bookmark` `:4577`, `bulk_delete_bookmarks` `:4598`,
`bulk_update_bookmarks` `:4619`, `bookmark_linked_dashboard_ids` `:4642`,
`get_bookmark_history` `:4672`); cohorts (App API) `:4736-4937` (`list_cohorts_app`
`:4736`, `get_cohort` `:4777`, `create_cohort` `:4807`, `update_cohort` `:4837`,
`delete_cohort` `:4868`, `bulk_delete_cohorts` `:4889`, `bulk_update_cohorts` `:4910`).

### TS homes

`packages/core/src/services/entities/{dashboards,bookmarks,cohorts}.ts` — each a
`create<Domain>Methods(core)` factory (R2.9 client-side halves that B6's
`create<Entity>Client({transport, getScope})` facade factories delegate to at W2/W3);
one spread line each appended in `client/client.ts`.

### Behavior spine

Every method routes through B0 `appRequest` (per-request auth via the session seam —
NEVER captured at construction, R2.9; 204 → `{status: "ok"}`; `results` unwrap via
`Object.hasOwn` when `_raw` is false; 422 → `QueryError` with lossless body) and the
workspace/project scoping helpers (`maybe_scoped_path`/`require_scoped_path` — B0/C1;
re-read each method for WHICH scoping it uses and whether `workspace_id` lands in params
instead of path). Bulk endpoints: exact body shapes (`ids` vs `entries` arrays), exact
HTTP verbs. `get_bookmark_history` and `list_bookmarks_v2` have query-param pagination
inputs — port the param spelling exactly; NO `paginate_all` anywhere in C3 (measured:
`paginate_all` has ZERO in-library call sites — see the C6 consumer note).

### Layer-3 translation scope (C3)

`tests/unit/test_api_client_crud.py` (1,059) — dashboards/bookmarks/cohorts + blueprint
classes (measured: blueprint tests live in `test_api_client_crud{,_edge}.py`, NOT in
`test_api_client_governance.py`, which is pure C5); `tests/unit/test_api_client_crud_edge.py`
(605); `tests/unit/test_api_client_bookmarks.py` (548).

### R10.10 consumers (C3)

37 of the 38 names have same-named B6 facade twins (W2 dashboards+advanced, W3
bookmarks/cohorts); the one exception: `list_cohorts_app` is consumed by
`workspace.list_cohorts_full` (`workspace.py:5548`, call at `:5583` — B6-W3).
Condensed rows (the full 37 rows are mechanically extractable —
`jq -c '.workspace_members[] | select(.name=="<name>") | {name,batch,params,kwonly,returns,ts_signature}' context/typescript-port-api-map.json`
— paste target for the B6 packets; representative rows here):

```json
{"name":"list_dashboards","batch":"B6","params":[],"kwonly":["ids"],"returns":"list[Dashboard]","ts_signature":"async list_dashboards(ids): Promise<list[Dashboard]>"}
{"name":"create_bookmark","batch":"B6","params":["params"],"kwonly":[],"returns":"Bookmark","ts_signature":"async create_bookmark(params): Promise<Bookmark>"}
{"name":"update_cohort","batch":"B6","params":["cohort_id","params"],"kwonly":[],"returns":"Cohort","ts_signature":"async update_cohort(cohort_id, params): Promise<Cohort>"}
{"name":"list_cohorts_full","batch":"B6","params":[],"kwonly":["data_group_id","ids"],"returns":"list[Cohort]","ts_signature":"async list_cohorts_full(data_group_id, ids): Promise<list[Cohort]>"}
```

Ergonomics consequence (same as every B6 row): the facade twins take TYPED params
objects and return rich result classes (`Dashboard`, `Bookmark`, `Cohort` — Phase-2/B1
types); the C3 client methods take/return the raw `body` dicts verbatim. The
B6-W3 `create_cohort`/`update_cohort` flattening and bookmark schema validation are
FACADE-side — C3 methods must NOT pre-shape or validate (the recorded request bodies
are already-flattened dicts; the vectors are the arbiter).

### R10.9 harness spec (C3) — `throwaway/b4-c3/`

§Wire rule branch list through `create_dashboard` (App-API representative) + one
scoped-path method with workspace pinned vs unpinned; 204-No-Content on the delete
family; `results`-unwrap vs `_raw`; bulk-body edge values (`[]`, `18.0` ids). RUN record.

### Done-criteria (C3)

Standard (tsc/check/tests/vectors 78 PASS/harness RUN/commits). Interim after
C1+C2+C3: **2,003 PASS / 0 FAIL**.

---

## Packet C4 — flags + experiments + annotations + webhooks + alerts (109 vectors)

**Model**: fable, ≤ high. **Vectors: 109** (46 names: flags 11/23v, experiments 12/25v,
annotations 7/20v, webhooks 5/13v, alerts 11/28v). 23 vectors carry C1 setups. Notes:
`context/phase3/notes/B4-C4-notes.md`.

### Python sources

`api_client.py:4938-6479`, in source order: feature flags `:4938-5276`
(`list_feature_flags` `:4938`, `create_feature_flag` `:4975`, `get_feature_flag`
`:5007`, `update_feature_flag` `:5039`, `delete_feature_flag` `:5072`,
`archive_feature_flag` `:5095`, `restore_feature_flag` `:5118`,
`duplicate_feature_flag` `:5150`, `set_flag_test_users` `:5182`, `get_flag_history`
`:5206`, `get_flag_limits` `:5241`); experiments `:5277-5673` (`list_experiments`
`:5277`, `create_experiment` `:5315`, `get_experiment` `:5348`, `update_experiment`
`:5381`, `delete_experiment` `:5417`, `launch_experiment` `:5441`,
`conclude_experiment` `:5474`, `decide_experiment` `:5511`, `archive_experiment`
`:5547`, `restore_experiment` `:5571`, `duplicate_experiment` `:5604`,
`list_erf_experiments` `:5640`); annotations `:5674-5919` (`list_annotations` `:5674`,
`create_annotation` `:5722`, `get_annotation` `:5757`, `update_annotation` `:5790`,
`delete_annotation` `:5826`, `list_annotation_tags` `:5853`, `create_annotation_tag`
`:5883`); webhooks `:5920-6077` (`list_webhooks` `:5920`, `create_webhook` `:5950`,
`update_webhook` `:5983`, `delete_webhook` `:6017`, `test_webhook` `:6041`); alerts
`:6078-6479` (`list_alerts` `:6078`, `create_alert` `:6122`, `get_alert` `:6155`,
`update_alert` `:6188`, `delete_alert` `:6222`, `bulk_delete_alerts` `:6246`,
`get_alert_count` `:6270`, `get_alert_history` `:6306`, `test_alert` `:6373`,
`get_alert_screenshot_url` `:6406`, `validate_alerts_for_bookmark` `:6439`).

### TS homes

`packages/core/src/services/entities/{flags,experiments,annotations,webhooks,alerts}.ts`
factories, spread into `client/client.ts` (one appended line each; or one
`create<Shard>Methods` per file grouped by domain — keep one exported factory per
domain file, R7.2).

### Behavior spine

All via B0 `appRequest`; string ids for flags/experiments (`flag_id: str`,
`experiment_id: str`) vs int ids for annotations/alerts — port the exact types
(R3-family; the api-map/`params` spellings are the contract). Verb/lifecycle
subtleties: archive/restore/duplicate/launch/conclude/decide use POST with specific
subpaths and some return `None` vs bodies — re-read each range; `delete_*` return
`None` (204 handling); `test_webhook`/`test_alert` POST bodies verbatim;
`get_alert_screenshot_url(gcs_key)` query-param encoding; `validate_alerts_for_bookmark`
POST body passthrough. Scoping: which of these are workspace-scoped
(`maybe_scoped_path`) vs project-scoped is per-method source truth — the recorded
request paths in the 109 vectors are the arbiter.

### Layer-3 translation scope (C4)

`tests/unit/test_api_client_flags.py` (623), `test_api_client_experiments.py` (637),
`test_api_client_annotations.py` (492), `test_api_client_webhooks.py` (393),
`test_api_client_alerts.py` (680) — ALL classes, all five files.

### R10.10 consumers (C4)

ALL 46 names have same-named B6 facade twins (measured: zero missing) — W4 (flags 11 +
experiments 12) and W5 (annotations 7 + webhooks 5 + alerts 11). Representative
condensed rows (full rows: the jq one-liner in the C3 packet, one per name):

```json
{"name":"create_feature_flag","batch":"B6","params":["params"],"kwonly":[],"returns":"FeatureFlag","ts_signature":"async create_feature_flag(params): Promise<FeatureFlag>"}
{"name":"decide_experiment","batch":"B6","params":["experiment_id","params"],"kwonly":[],"returns":"Experiment","ts_signature":"async decide_experiment(experiment_id, params): Promise<Experiment>"}
{"name":"validate_alerts_for_bookmark","batch":"B6","params":["params"],"kwonly":[],"returns":"ValidateAlertsForBookmarkResponse","ts_signature":"async validate_alerts_for_bookmark(params): Promise<ValidateAlertsForBookmarkResponse>"}
```

(Typed-wrapper note as in C3: facade `params` objects/rich returns vs the C4 client
methods' raw dict bodies.)

### R10.9 harness spec (C4) — `throwaway/b4-c4/`

§Wire rule branch list through `create_alert` (App-API representative) + the 204/none
returns on the delete/archive family + `get_alert_history` param grid + edge values in
POST bodies (empty body `{}`, `[]` ids, `"𝒳"` names). RUN record.

### Done-criteria (C4)

Standard; all 109 vectors PASS. Interim after C1+C2+C3+C4: **2,112 PASS / 0 FAIL**.

---

## Packet C5 — data governance + schemas + audit/anomalies/deletion + business context + replays signing (219 vectors)

**Model**: fable, ≤ high. **Vectors: 219** (64 names; heaviest: schemas block 51,
lexicon definitions/tags/history 45, lookup tables 28, custom events 19). 2 vectors
carry C1 setups. Notes: `context/phase3/notes/B4-C5-notes.md`.

### Python sources

Two disjoint ranges (the shard owns both):
- Schemas: `api_client.py:3294-3649` (`get_schemas` `:3294`, `get_schema` `:3345`,
  `list_schema_registry` `:3398`, `create_schema` `:3437`, `create_schemas_bulk`
  `:3480`, `update_schema` `:3517`, `update_schemas_bulk` `:3560`, `delete_schemas`
  `:3594-3649`).
- Governance tail: `api_client.py:6480-8894` — lexicon definitions `:6480-6900`
  (`_event_definitions` `:6480` + `_property_definitions` `:6669` private shared cores —
  plain `app_request` GETs with `name[]` filters + a bare-list shape check raising
  `MixpanelHeadlessError` on non-list; measured: NO `paginate_all` involvement;
  `get_event_definitions`
  `:6515`, `list_event_definitions` `:6541`, `update_event_definition` `:6565`,
  `delete_event_definition` `:6604`, `bulk_update_event_definitions` `:6628`,
  `get_property_definitions` `:6738`, `list_property_definitions` `:6770`,
  `update_property_definition` `:6821`, `bulk_update_property_definitions` `:6860`);
  lexicon tags/metadata/export `:6901-7177` (`list_lexicon_tags` `:6901`,
  `create_lexicon_tag` `:6931`, `update_lexicon_tag` `:6964`, `delete_lexicon_tag`
  `:6998` — deletes BY NAME, not id, `delete_lexicon_tag(self, name: str)`;
  `get_tracking_metadata` `:7022`, `get_event_history` `:7055`, `get_property_history`
  `:7090`, `export_lexicon` `:7128`); drop filters `:7178-7344`; custom properties
  `:7345-7545`; lookup tables `:7546-7987` (`upload_to_signed_url` `:7625` — raw PUT to
  an EXTERNAL signed URL, not a Mixpanel host: no auth header, no `_execute_with_retry`;
  `download_lookup_table` `:7874` + `get_lookup_download_url` `:7937` — redirect-bearing
  endpoints: R2.11 `redirect: 'manual'` interplay, re-read how Python follows/captures
  the Location; `register_lookup_table`/`mark_lookup_table_ready` `:7683`/`:7748` use
  FORM bodies); custom events `:7988-8169` (incl. index-absent `list_custom_events`
  `:8038`); schema enforcement `:8170-8344`; audit `:8345-8421`; anomalies `:8422-8543`;
  deletion requests `:8544-8680`; business context `:8681-8836` (index-absent, three
  methods); `sign_replays` `:8837-8894` (the 403 `SESSION_RECORDING_SENSITIVE_DATA` →
  `SessionReplayAccessError` consumer surface — the method itself delegates to
  `app_request` POST; the 403 branch lives in B0 `handleResponse` — nothing to
  re-implement, everything to lock). NOTE: the B0 R10.8 ownership call sites `:7720`
  and `:7923` are the lookup-table `download_lookup_table`/`get_lookup_download_url`
  direct-request paths — they build headers via B0 `requestHeaders` with explicit
  Authorization (+ `Accept-Encoding: gzip` on download) extras and route non-2xx
  through `handleResponse` manually, bypassing `_execute_with_retry`; port that wiring
  verbatim.

### TS homes

`packages/core/src/services/entities/{schemas,lexicon,drop-filters,custom-properties,lookup-tables,custom-events,schema-enforcement,audit,anomalies,deletion-requests,business-context,replays-signing}.ts`
factories (group small domains per file as sensible under R7.2, one exported factory
per file), spread into `client/client.ts`.

### Behavior spine

App-API via B0 `appRequest` throughout, EXCEPT: `upload_to_signed_url` (external PUT,
csv bytes body, no Mixpanel envelope — transport-adapter path with R2.10 normalization
only), `download_lookup_table`/`get_lookup_download_url` (re-read redirect semantics
verbatim), form-body endpoints (`register_lookup_table`, `mark_lookup_table_ready` —
the B0 deferral `test_form_body_sent_as_form_encoded` content-type assertion is C1's
translation but THESE are the production consumers: assert the adapter sets
`application/x-www-form-urlencoded` end-to-end here too). `run_audit`/
`run_audit_events_only` return `list[Any]`; `create_drop_filter`/`update_drop_filter`/
`delete_drop_filter`/`cancel_deletion_request` return LISTS (not dicts) — no
results-unwrap surprises: port exactly what `_handle_response`/`appRequest` hand back.
`sign_replays(replay_ids, env=…)`: exact param spelling and the project_id int coercion
in details (`pythonInt`, B0 branch). Watch `delete_schemas` (bulk via body) vs
`delete_schema_enforcement` (no args).

### Layer-3 translation scope (C5)

`tests/unit/test_api_client_data_governance.py` (2,375 — ALL classes, :60-2375),
`tests/unit/test_api_client_governance.py` (1,097 — ALL: schema enforcement :60-350,
audit :351-594, anomalies :595-856, deletion requests :857-1097),
`tests/unit/test_api_client_schemas.py` (1,044 — ALL),
`tests/unit/_internal/test_api_client_sign_replays.py` (250 — ALL; the
TestSensitiveDataMapping/TestOtherHttpErrors halves were translated at B0 against
`handleResponse` — header exclusion for exactly those, cite `b0-review-assertions.md`;
the sign_replays METHOD tests translate here).

### R10.10 consumers (C5)

58 of the 64 names have same-named B6 facade twins (W6a lexicon+tracking, W6b drop
filters/custom properties/lookup tables/custom events, W7 schemas/enforcement/audit/
anomalies/deletion). The six exceptions (measured): `get_schemas`/`get_schema` →
DiscoveryService `list_schemas`/`get_schema` (B5-S1);
`list_event_definitions`/`list_property_definitions` → DiscoveryService
`get_schema_graph` (B5-S1); `upload_to_signed_url`/`register_lookup_table` →
`workspace.upload_lookup_table` (`workspace.py:8045`, `:8056` — B6-W6b). Plus
`sign_replays` → ReplaysService `sign` (`services/replays.py:208`) and the B5 members
`sign_replay`/`sign_replays` (S3). Representative condensed rows:

```json
{"name":"create_custom_event","batch":"B6","params":["params"],"kwonly":[],"returns":"CustomEvent","ts_signature":"async create_custom_event(params): Promise<CustomEvent>"}
{"name":"export_lexicon","batch":"B6","params":[],"kwonly":["export_types"],"returns":"dict[str, Any]","ts_signature":"async export_lexicon(export_types): Promise<Record<string, unknown>>"}
{"name":"upload_lookup_table","batch":"B6","params":["params"],"kwonly":["poll_interval","max_poll_seconds"],"returns":"LookupTable","ts_signature":"async upload_lookup_table(params, poll_interval, max_poll_seconds): Promise<LookupTable>"}
{"name":"sign_replay","batch":"B5","params":["replay_id"],"kwonly":["env"],"returns":"SignedReplay","ts_signature":"async sign_replay(replay_id, env): Promise<SignedReplay>"}
{"name":"sign_replays","batch":"B5","params":["replay_ids"],"kwonly":["env"],"returns":"list[SignedReplay]","ts_signature":"async sign_replays(replay_ids, env): Promise<list[SignedReplay]>"}
```

### R10.9 harness spec (C5) — `throwaway/b4-c5/`

§Wire rule branch list through `create_schema` (App-API representative) +
`sign_replays` 403-sensitive-data AND the R10.7 bug-compat matrix (403 bodies `42`,
`1.5`, `true` → TypeError-analog throw; `0`/`false`/`null` → QueryError;
`["SESSION_RECORDING_SENSITIVE_DATA"]` exact-element vs
`["x…y"]` substring-miss — the B0 harness cases re-exercised through the REAL
sign_replays method) + `upload_to_signed_url` external-PUT (no auth header assert) +
form-encoding on `register_lookup_table` + list-returning endpoints + edge values. RUN
record.

### Done-criteria (C5)

Standard; all 219 vectors PASS. Interim after C1–C5: **2,331 PASS / 0 FAIL**.

---

## Packet C6 — pagination.py (39 vectors; after C1)

**Model**: fable, ≤ high. **Vectors: 39**, all `pagination.paginate_all`
(`corpus/pagination/test_pagination.jsonl`). Notes:
`context/phase3/notes/B4-C6-notes.md`. C6 owns the `pagination.` batch-status prefix
(flipped at the gate together with `api_client.`).

### Python source

`src/mixpanel_headless/_internal/pagination.py` (288 LOC, whole file):
constants `MAX_PAGES = 10000` `:35`, `MAX_RATE_LIMIT_RETRIES = 3` `:38`,
`_BACKOFF_BASE = 1.0` `:41`, `_BACKOFF_MAX = 60.0` `:44`; module-level
`_parse_retry_after(raw: str | None) -> float | None` `:47-83` — **NOT the client's
response-based `_parse_retry_after`** (string input, FLOAT parse: `float(raw)` →
`pythonFloat` per R11.7, then reject non-finite/negative — `"inf"` parses then filters
to None; value NOT capped here); `paginate_all(client, path, *, params=None,
page_size=100)` `:85-288`.

**Measured spine (byte-for-byte; this function does NOT go through
`app_request`/`executeWithRetry` — port its private wiring verbatim):**
- Per page: `request_params = {page_size: str(page_size), …params, cursor?}` with
  `request_params["query_origin"] = "mixpanel-headless"` set LAST (caller params can't
  override; literal string here, `:157-158`); URL via `client._build_url("app", path)`
  (B0 `buildUrl`); headers are the LITERAL `{"Authorization": client._get_auth_header()}`
  — **no `_request_headers` merge, no User-Agent** (`:161-163` — a real divergence from
  the client methods; the recorded vectors lock it);
  raw `http_client.request("GET", …)` on the C1 client's transport (per-request auth,
  R2.8).
- Its OWN 429 loop `:168-217` (R6.1): `for attempt in 0..MAX_RATE_LIMIT_RETRIES`;
  exhausted → `RateLimitError` with `retry_after = int(advertised)` (float→int
  truncation) or None, `status_code=429`, `response_body=response.text`,
  `request_method`, `request_url` — **NO `project_id`, NO `request_params`** (this
  raise site is NOT one of Caution #3's five; port the reduced shape verbatim). Wait
  time: advertised present → `min(advertised, 60)`; absent → `min(1.0 * 2^attempt,
  60)` — **NO jitter in either path** (unlike the client backoff; do not import
  `calculateBackoff`'s jitter).
- `httpx.HTTPError` mid-pagination → `MixpanelHeadlessError` code **`NETWORK_ERROR`**
  (not `HTTP_ERROR` — different from `_execute_with_retry`'s mapping) with
  `{path, error}` details `:177-182`.
- Non-429 non-2xx via `raise_for_status` catch `:219-244`: 401 →
  `AuthenticationError`; ≥500 → `ServerError`; else `MixpanelHeadlessError` code
  **`API_ERROR`** with `{status_code, response_body}` details.
- Body: `response.json()` → TS `parseLossless(text, { pythonConstants: true })`;
  failure → `INVALID_RESPONSE` with `{content_type}` detail `:246-254`.
- Results extraction `:256-278`: dict body — `results` absent OR null → `[]` (cursor,
  not this field, ends iteration); list → yield; anything else → `INVALID_RESPONSE`
  with `{path, results_type}`; a top-level LIST body yields directly. `yield from
  results` = item-level `yield*` (R6.6).
- `next_cursor` from `data.pagination.next_cursor` only when `pagination` is a truthy
  dict; None → break. Page counter at the loop head `:142-150`: `page_count > MAX_PAGES`
  → `MixpanelHeadlessError` code **`PAGINATION_LIMIT`** with `{max_pages, path}` details.

### TS home

`packages/core/src/client/pagination.ts` — `async function* paginateAll(...)` (R6.1:
`for await` consumable, lazy; R6.6 item-level `yield*`; R6.7 AbortSignal at all four
points — between pages, into the request, into the backoff sleep, normalized exit with
`DOMException(…, 'AbortError')`). Takes the C1 client instance exactly as Python takes
`client` and uses the client's own url/auth/transport internals per the measured spine
above — per-request auth resolution preserved (R2.8). NOTE the B0-2 R10.10 note
described a "`PageFetcher`-style function seam over `app_request`" — source truth
(measured above) is RAW transport requests that bypass `app_request`; the note's
intent (per-request auth via a function seam) stands, its mechanism is corrected here.
R2.12: sleep in ms at the seam; the parsed Retry-After stays seconds under its Python
name.

### Layer-3 translation scope (C6)

`tests/unit/test_pagination.py` (824) — ALL: cursor threading, page_size, empty pages,
null cursor termination, cursor-loop/repeat protection (re-read: does the source guard
repeated cursors? port exactly), 429-retry-inside-pagination timing (fake timers),
malformed envelopes. **MAX_PAGES patch-test replacement (playbook B4 row)**: Python
tests that `monkeypatch` `MAX_PAGES` down to a small value must translate via an
injectable `maxPages` option (default 10000) on `paginateAll` — an option, not a
mutable module global; assertion content (the limit error fires at page N+1, code
preserved) unchanged. Dedicated async Layer-3 (plan §7): delayed mock pages, abort
between pages, abort during backoff sleep.

### R10.10 consumers (C6)

**Measured: `paginate_all` has ZERO in-library call sites** (grep over
`src/mixpanel_headless/` — only its own module and `tests/unit/test_pagination.py`
reference it; the docstring's dashboards example is illustrative). Its consumers are
end users + the 39 recorded vectors + the Layer-3 suite. Consequence: keep the
module's documented "use the client methods instead" posture (R7.2) — export
`paginateAll` from `packages/core/src/client/pagination.ts` mirroring the Python
module's importability, but wire it into no client method (a shard that "helpfully"
routes lexicon listing through it would diverge from every recorded request
sequence).

### R10.9 harness spec (C6) — `throwaway/b4-c6/`

Hand-built interaction sequences: 1-page, 3-page, empty-results page, `results: null`,
missing pagination block, next_cursor repeat, 429-then-success mid-pagination,
429×4-exhausted (per-paginator retry ×3), >maxPages overflow (with injected small
maxPages), edge values in `params`. RUN record.

### Done-criteria (C6)

Standard; all 39 vectors PASS. Interim after all six shards: **2,370 PASS / 0 FAIL /
881 UNPORTED** — the gate flip then converts nothing (no stragglers) and the report
checkpoint must reproduce those exact counts.

---

## Cautions — the CRITICAL RULES block, with cites (binding on every shard; review-pair checklist)

1. **GATE-VERDICT R5 + B0 arbiter F1 (lossless everywhere)**: ALL wire body parsing via
   `parseLossless` (`packages/core/src/client/lossless-json.ts:76`) — zero
   `response.json()` / bare `JSON.parse` on response text in `packages/*/src`
   (`wirestub.ts:198` is the sole grandfathered test double; grep-audited at review,
   P3-2 b′). Use `{ pythonConstants: true }` at every site where Python calls
   `json.loads` on WIRE data (existing sites: `internals.ts` handleResponse parse,
   `app-request.ts:227`; NEW at B4: C2's per-JSONL-line parse — Python
   `api_client.py:1931` — and the export-429 body parse `:1911`; see the `jsonl.ts`
   JSDoc and `lossless-json.ts:14`). JSONDecodeError-analog catches carry the
   `instanceof LosslessJsonError` guard (B0-ARB F3; RangeError propagates).
2. **R10.7 bug-compat, the 403-TypeError branch** (bug report
   `context/phase3/bug-reports/python-handle-response-403-typeerror.md`, OPEN):
   `_handle_response` 403 with truthy non-dict/non-str JSON body (`42`/`1.5`/`true`)
   raises TypeError in Python (`api_client.py:565-570`); list bodies use EXACT-ELEMENT
   membership; falsy scalars take the QueryError path. The TS twin (B0
   `internals.ts`) REPLICATES this — B4 must NOT "fix" it, must not route around it,
   and C5's sign_replays harness re-exercises the matrix through the real method. No
   corpus vector locks these bodies — Layer-3 + harness only.
3. **RateLimitError `project_id` at ALL FIVE raise sites** (packet FF4): `:779`, `:819`
   (`_execute_with_retry` — B0, already landed), `:1322`, `:1386` (`app_request` — B0),
   `:1883-1891` (export_events streaming — **C2's deferral**). Constructor shapes per
   site: the type-checker fallthroughs `:814-820`/`:1381-1387` omit
   `retry_after`/`status_code`/`response_body`; the streaming site omits
   `response_body` only. Corpus `details_contain` does NOT assert `project_id` — only
   the Layer-3 locks do (`test_api_client.py:504`, `:527`, `:1567`, `:4090`): translate
   them without weakening (R10.2).
4. **`_error_message` rules** (packet FF6; `api_client.py:81-106`, B0
   `internals.ts:294` `errorMessage`): dict body with `error` ABSENT **or null** →
   default (never the string `"None"`); string `error` as-is; other non-null →
   `pythonStr`; string body → `cpSlice(body, 0, 200)`; blank-after-`pythonStrip` →
   default. C-shards consume it via `handleResponse` — never re-derive messages, and
   never vector-assert message text (R5.4).
5. **R2.10 / R2.11 / R2.12 / R2.13**: transport failures normalized to
   `MixpanelHttpError` in the fetch adapter — NO bare catch, `if (!(e instanceof
   MixpanelHttpError)) throw e;` then wrap as `HTTP_ERROR` (R2.10); `redirect:
   'manual'` + throwing raise_for_status analog — a 3xx with a JSON body is an ERROR,
   never a success (R2.11; B0 `internals.ts` fallthrough order `api_client.py:652-662`);
   milliseconds ONLY at the sleep seam, `*Seconds` Python names in serialized details
   (R2.12); URLs by string concatenation, never `new URL(path, base)` (R2.13; B0
   `url.ts`).
6. **R6.7 AbortSignal at all four points** via the signal-aware `request`/`sleep`
   closures WITHOUT touching B0 signatures (B0-ARB carried item 6a — the GATE verifies
   it landed): between pages (C6), into the request (C1 adapter), into the backoff
   sleep (C1 wrapper), normalized on exit as `DOMException(…, 'AbortError')` (a plain
   `Error` from a sleep evades name-based checks).
7. **B0 deviation-3 deferrals — B4 MUST land every one** (B0-ARB carried item 6b; the
   gate diff-checks this list): TestRetryStateResetRegression ×4
   (`test_api_client.py:1401` — C2); streaming project_id raise `:1883-1891` +
   Layer-3 lock `test_api_client.py:1560-1575` (C2);
   `test_export_events_negative_retry_after_uses_backoff` `:3810` (C2);
   `test_form_body_sent_as_form_encoded` content-type assertion
   (`test_app_api_client.py:316` — C1, adapter-owned; C5's form endpoints are the
   production exercise); auth-header wire captures (Bearer/Basic end-to-end — C1, real
   via `clientFromSession`).
8. **R11.7 `[SA3]`**: every `not s.strip()` → `pythonStrip`; every `int(str)` →
   `pythonInt`; bare `String.trim()`, `parseInt`, `Number(...)`, `\s`-regex grammars
   are FORBIDDEN in ported code (the pattern recurred 13× at the B0 gate — rulebook
   `:345`). Applies to C6's `_parse_retry_after(raw)` and every param-coercion site.
9. **Watchlist #13 `isPythonDict`** (rulebook `:235-245`): every `isinstance(x, dict)`
   discrimination imports `isPythonDict` from `query/validation-shared.ts` — never a
   `typeof`/`Array.isArray` re-derivation. For client-internal plain-JSON checks B0
   also exports `isPlainRecord` (`internals.ts:153`) — use the one matching the Python
   predicate being ported (isinstance-of-dict vs "JSON object body").
10. **Playbook Discrepancy #1 (jitter)**: Retry-After header path is UNJITTERED
    `min(pythonFloat(int), 60)`; the fallback is jittered `min(1.0*2^attempt, 60) +
    uniform(0, delay*0.1)` via the injected `random` seam. Discrepancy #6: Retry-After
    beyond 2^53−1 reads as ABSENT in TS (sanctioned; do not "improve").
11. **No result pre-shaping**: C-shard methods return what `handleResponse`/`appRequest`
    hand back (dict/list/scalar passthrough). Result classes (`SegmentationResult`,
    `Dashboard`, …) are B5/B6 facade work — pre-shaping here would double-transform at
    B5/B6 and fail their vectors.
12. **R10.2 test translation**: never weaken an assertion; unportable → `// TODO(port)`
    + escalate; per-file header exclusions must cite this packet or a design doc
    (phase2-audit A2 style). Python `monkeypatch.setattr(client, "_calculate_backoff",…)`
    pins translate to injected-RNG-deterministic values (B0 deviation-5 precedent);
    `MAX_PAGES` monkeypatch → injectable `maxPages` option (C6).
13. **Recorded-header exactness**: fake creds make byte-exact auth-header diffs safe;
    if a vector FAIL_REQUESTs on an auth header, the bug is in `clientFromSession`/
    Phase-2 `accountAuthHeader` wiring — fix the seam, never special-case the binding.

---

## Batch gate task (P3-2 e, instantiated for B4) — one fable task after all six arbiters

1. **183-name assignment audit** (risk-register #1): mechanical diff — union of this
   packet's six lists == `jq -r 'keys[]|select(startswith("api_client."))'
   corpus/api-index.json | sort` (183 names, each bound exactly once in
   `bindings.ts`); PLUS grep the shards for local re-implementations of
   `_handle_response`/backoff/URL-building/header-merging (must import B0 by name).
2. **Flip** `api_client.` + `pagination.` → `done` in the gate-checkpoint commit;
   standing collision assertion + prefix-coverage unit test green (§Wire-enablement
   flip spec; record the B5 `list_bookmarks_v2` forward note in the gate notes).
3. **Conformance checkpoint**: `npm run conformance` → **2,370 PASS / 0 FAIL / 881
   UNPORTED** (delta +842/−842 exactly); archive report JSON to
   `context/phase3/reports/2026-MM-DD-b4-gate.json` (Python repo, support branch);
   commit both repos.
4. **Oracle probe**: wire names are EXEMPT (no oracle call surface — P3-2 e item 3);
   then the differential full-suite regression (cumulative surface, fresh seeds, ≥500
   per family) — zero unexplained divergences; RUN record to
   `conformance/differential/oracle/RUN.md`.
5. **B0-ARB carried items verified**: (a) R6.7 signal-aware closures landed without B0
   signature changes; (b) every deviation-3 deferral (Caution #7 list) present in the
   translated suites.
6. `npm run check` green; `just check` green (Python touched: notes/reports).
7. `throwaway/b4-c1..c6/` removed after arbiter sign-off (+ any eslint throwaway-glob
   revert); `context/phase3/notes/B4-notes.md` finalized (RUN records, findings,
   discrepancies, escalations).
8. Referees (a)/(b): NOT required at B4 (bookmark-touching batches are B3/B6; C3's
   bookmark CRUD transports pre-built bodies and constructs none) — state for the
   record, per the B0-gate precedent.

## Review checklist deltas (P3-2 d, per shard — beyond the standard five items)

- Binding honesty: every binding = memoized `clientFromSession` + one client-method
  call + kwarg passthrough (P3-5 §3); anything assembling paths/params in a binding is
  a finding.
- GATE-R5 grep (item 3) extended with the `pythonConstants` site audit (Caution #1).
- The Caution #3 constructor-shape check per raise site.
- C2: R6.6 item-level `yield*`; AsyncIterable early-return; no `query_origin`
  double-injection.
- C5: external-PUT has NO Mixpanel auth header; form-encoded content-type end-to-end.
- C6: `maxPages` injectable, default 10000; per-paginator 429 retry ×3 independent of
  client `max_retries`.



