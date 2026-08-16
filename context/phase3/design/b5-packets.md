# B5 packets (design-lite) — services + rrweb analyzer + the workspace query half

**Status**: v1.0 · 2026-08-16 · B5-DL output (playbook P3-6 step 1, fable).
Instantiates the playbook B5 row (`phase3-playbook.md:190-208`), the P3-6 B5
sharding table (`:746-751`), the P3-5 flip rules (`:649-659`), and the
P3-1 † cross-batch-setup footnote (`:93-102`). Every count below was
MEASURED 2026-08-16 against corpus pin `70c904dc` (TS repo
`conformance-runner/corpus.config.json`); the B4-gate baseline is
**3,251 vectors — 2,370 PASS / 0 FAIL / 881 UNPORTED**
(`context/phase3/reports/2026-08-16-b4-gate.json`).

Builders MUST re-read every cited Python range (P3-1: the packet pastes
signatures, but source is the spec). Python repo branch
`ts-port/phase2-contract-support`; TS repo branch `main`. LOCAL COMMITS ONLY.

---

## §0 Batch invariants (apply to S1/S2/S3 alike)

1. **Tiering (P3-3, revised 2026-08-15)**: S1/S2/S3 module tasks + their
   Layer-3 translations = **opus**, effort ≤ high. Binding+oracle task (b′),
   review pair ×2, arbiter, gate = **fable**. R10.13 incremental protocol on
   every agent (skeleton first, small frequent edits, notes file). NO
   mutation testing `[SA1]`. `/Users/jaredmcfarland/Developer/analytics` is
   READ-ONLY (S3 may READ `iron/replay-embed/__test__/fixtures.ts` for
   fixture extraction per plan §Layer-3, `typescript-port-plan.md:351-354`).
   Python via `uv`; bare `python` and the literal p-y-t-e-s-t string are
   hook-blocked (`uv run python -m pytest`).
2. **Lossless body parsing (GATE-R5 + B0-1 F1)**: every wire response body —
   including the S3 CDN payloads (`replays.py:465` `response.json()`) —
   parses via `parseLossless` with `pythonConstants: true` (CPython
   `json.loads` accepts `NaN`/`Infinity`/`-Infinity`;
   `b0-review-resolution.md` F1 precedent, applied throughout B4). Never
   `response.json()` / bare `JSON.parse` in `packages/*/src`.
3. **W-F6 ruling (B4 arbiter, `B4-notes.md:49`)**: injected-sleep seam for
   ALL retry timing; real short delays only where wall-clock passage is
   itself the observable. No real timers in tests (Vitest fake timers).
4. **Determinism seams**: services thread the client's injected
   `now`/`random`/`sleep` seams (P3-5 §2: bindings pass
   `now: () => recordEpoch`, `random: () => 0`, zero-delay sleep). Python
   clock sites that MUST route through `now`:
   `discovery.py:889` (`schema_graph` `computed_at =
   datetime.now(timezone.utc).isoformat()`), `replays.py:207`
   (`sign` `signed_at = time.time()`). There are no UUID sites in the three
   services (measured grep 2026-08-16); the transforms' determinism is pure
   input→output.
5. **R11.7 / watchlist #13**: every Python `not s.strip()` blank check ports
   via `pythonStrip` (rulebook `:345`); `int(str)` coercions via `pythonInt`;
   dict-vs-instance discrimination imports `isPythonDict` (rulebook `:241-244`
   — the unified helper; never a local re-implementation).
6. **R4.3**: the four rrweb `IntEnum`s (`rrweb_analyzer.py:52,61,71,81` —
   `EventType`, `IncrementalSource`, `MouseInteractionType`, `NodeType`)
   port as `const` objects + literal unions preserving numeric values
   (rulebook `:114-118`).
7. **R6.6**: facade generator members (`workspace.stream_replay`
   `workspace.py:10983`, service generator `walk_cdn_async`
   `replays.py:277`) port as item-level `yield*` — never buffer.
8. **R10.8 imports, never re-implement**: B5 composes the B4 client
   (`packages/core/src/client/client.ts` — domain methods already attached
   at the marked append-only merge point). The service delegate names are
   client methods that EXIST; S-shards import them via the assembled
   `MixpanelClient`, never re-assemble requests. `response_validation.py`
   is ALREADY PORTED at B4-C1 (`client/response-validation.ts` header,
   `B4-C1-notes.md:101-103`) — S1/S2 IMPORT it; the playbook B5-row listing
   of that module is satisfied by the import, not a re-port.
9. **A-F2 binding instruction (B4 arbiter, `b4-packets.md:1186-1190`)**:
   every Layer-3 file below is enumerated against its COMPLETE
   `grep -n '^class '` output; every class has an owner or a cited
   exclusion. Shard implementers keep the file headers in that style
   (phase2-audit A2 citations).
10. **Discrepancy #8 boundary (ratified)**: fuzz domains stay
    annotation-constrained; out-of-annotation CPython raises are
    unspecified. Discrepancies #9/#10 exclusions (integer-like unknown
    keys) carry into any S2 fuzz families that route params dicts.

---

## §1 Measured vector budget (sums to exactly 506)

Per-api counts, corpus pin `70c904dc` (all 44 `workspace.<member>` names from
`jq -r '.workspace_members[] | select(.batch=="B5") | .name'
context/typescript-port-api-map.json` — 44 names confirmed):

| api (S2 — 22 query members) | vectors | | api (S1 — 12 discovery/lexicon) | vectors |
|---|---|---|---|---|
| workspace.build_params | 143 | | workspace.events | 0 |
| workspace.build_funnel_params | 95 | | workspace.properties | 0 |
| workspace.build_user_params | 80 | | workspace.property_values | 0 |
| workspace.build_retention_params | 55 | | workspace.subproperties | 0 |
| workspace.build_flow_params | 53 | | workspace.funnels | 0 |
| workspace.query_saved_report | 37 | | workspace.cohorts | 0 |
| workspace.query_saved_flows | 6 | | workspace.list_bookmarks | 0 |
| workspace.retention | 3 | | workspace.top_events | 0 |
| workspace.funnel | 3 | | workspace.clear_discovery_cache | 0 |
| workspace.segmentation_sum | 1 | | workspace.lexicon_schemas | 0 |
| workspace.segmentation_numeric | 1 | | workspace.lexicon_schema | 0 |
| workspace.segmentation_average | 1 | | workspace.schema_graph | 0 |
| workspace.frequency | 1 | | **S1 subtotal** | **0** |
| workspace.activity_feed | 1 | | | |
| workspace.segmentation | 0 | | **api (S3 — replays family)** | |
| workspace.event_counts | 0 | | replays.fetch_files | 8 |
| workspace.property_counts | 0 | | replay_labels.url_normalizer | 12 |
| workspace.query | 0 | | replay_labels.default_label_fn | 4 |
| workspace.query_funnel | 0 | | rrweb_analyzer.analyze | 2 |
| workspace.query_flow | 0 | | workspace.list_replays … analyze_replay (all 10 members) | 0 |
| workspace.query_retention | 0 | | **S3 subtotal** | **26** |
| workspace.query_user | 0 | | | |
| **S2 subtotal** | **480** | | **BATCH TOTAL** | **506** |

Checks: 143+95+80+55+53 = **426** (the five builders — the playbook's
"volume center", `:748`); +37+6+3+3+1+1+1+1+1 = **480** = the P3-1 measured
B5-member share of `workspace.*`. 8+12+4+2 = **26** = `replays.` 8 +
`replay_labels.` 16 + `rrweb_analyzer.` 2 (P3-1 row). 480+0+26 = **506**. ✓

Per-corpus-file distribution (38 files, measured; sums 506): authored —
`funnels/live-query-transforms.jsonl` 3, `retention/live-query-transforms.jsonl` 3,
`parse/phase008.jsonl` 6, `parse/storybook/arb_funnels.jsonl` 6,
`parse/storybook/insights.jsonl` 36, `replays/rrweb-seed.jsonl` 2; recorded —
`bookmarks/test_build_cohort_params` 43, `bookmarks/test_custom_property_builders` 4,
`bookmarks/test_custom_property_query` 8, `bookmarks/test_custom_property_types` 16,
`bookmarks/test_query_integration` 2, `bookmarks/test_query_params` 32,
`bookmarks/test_query_validation` 10, `bookmarks/test_validation_bypass` 16,
`bookmarks/test_validation_bypass_r2` 2, `bookmarks/test_workspace_cohort` 10,
`engage/test_query_user_edge_cases` 9, `engage/test_workspace_build_user_params` 68,
`engage/test_workspace_query_user_integration` 3, `flows/test_build_cohort_params` 10,
`flows/test_validation_bypass_r2` 4, `flows/test_workspace_cohort` 8,
`flows/test_workspace_flow` 31, `funnels/test_build_cohort_params` 4,
`funnels/test_build_funnel_params` 79, `funnels/test_custom_property_query` 2,
`funnels/test_custom_property_types` 2, `funnels/test_validation_bypass` 3,
`funnels/test_workspace_funnel` 5, `replays/test_replay_bundle` 15,
`replays/test_replays_service` 8, `replays/test_rrweb_analyzer` 1,
`retention/test_build_cohort_params` 5, `retention/test_build_retention_params` 39,
`retention/test_custom_property_query` 1, `retention/test_custom_property_types` 2,
`retention/test_validation_bypass_r2` 4, `retention/test_workspace_retention` 4.

**Setup gating (P3-1 †)**: measured 2026-08-16 — ZERO of the 506 B5 vectors
carry a `call.setup[]` entry (the only workspace-measured setup carriers are
B6 flag-family vectors with `api_client.set_workspace_id` setups). The B5
**gate delta is therefore exactly 506**: expected post-flip report
**2,876 PASS / 0 FAIL / 375 UNPORTED**. The carried holdback vector
(`auth/api_client.resolve_workspace_id/...` with setup `workspace.me`)
stays UNPORTED through this gate (`workspace.me` is **B6** — see §6).

---

## §2 Sequencing and the workspace.ts merge plan

**S2 runs FIRST** (it creates `packages/core/src/workspace.ts` — the class
skeleton + its own 22 members). **S1 and S3 then run in PARALLEL**; each
extends `workspace.ts` in its own marked append-only member section
(risk-register #6 mitigation — same pattern as the B4 client merge point,
`client.ts:1072`). Section markers, in file order:

```
// === B5-S2 query members (this shard) ===
// === B5-S1 discovery/lexicon members (append-only; S1 owns) ===
// === B5-S3 session-replay members (append-only; S3 owns) ===
// === B6 members land below in W1–W7 sections (append-only) ===
```

Skeleton contract (S2 builds; S1/S3/B6 must not touch):

- `class Workspace` with constructor mirroring the replay path
  `Workspace(session=…, _api_client=…)` (`workspace.py:424-432`;
  conformance twin `conformance/runner/targets.py:316-328`). TS shape:
  `new Workspace({ session, client? })` — `client` is the injected
  `MixpanelClient` test/replay seam; when absent the constructor builds one
  via `createMixpanelClient({session, …seams})`. Account/project/target
  resolution axes are **B7** — the B5 constructor takes a resolved `Session`
  only, and the ctor kwargs `account/project/workspace/target`
  (`workspace.py:427-430`) surface at B6/B7; leave a cited TODO(port).
- `use()` / `close()` / `[Symbol.asyncDispose]` **stubs marked B6-owned**
  (throw `MixpanelHeadlessError` code `UNPORTED_MEMBER` with a
  `// TODO(port): B6-W1` marker — zero B5 vectors and zero B5 Layer-3
  classes reach them; `TestDiscoveryCacheAcrossUse` defers, §3.2).
- Lazy service accessors mirroring `_discovery_service`/`_live_query_service`/
  `_replays_service` (`workspace.py:1006-1037`): private memoized fields; the
  replays accessor wires `query_fn` to the bound `query` member exactly as
  Python does (circular-import-free DI, `replays.py:150-176`).
- `clear_discovery_cache` (`workspace.py:1273`) is S1's member but the cache
  lives on the S1 service — the skeleton only reserves the S1 section.

---

## §3 Packet S2 — LiveQueryService + workspace.ts skeleton + the 22 query members (opus)

### Scope / Python sources (re-read all ranges)

| Source | Ranges | Content |
|---|---|---|
| `_internal/services/live_query.py` (2,042) | module functions `:51-674` (`_extract_steps_from_date_data` :51, `_transform_funnel` :80, `_transform_retention` :159, `_transform_segmentation` :222, `_transform_query_result` :262, `_extract_funnel_steps_from_series` :313, `_transform_funnel_result` :443, `_normalize_cohort_date` :498, `_extract_cohorts_and_average` :514, `_transform_retention_result` :537); `class LiveQueryService` `:677-1565` (16 query methods); tail transforms `:1567-2042` (`_transform_activity_feed` :1567, `_transform_saved_report` :1623, `_transform_flow_result` :1698, `_parse_tree_node` :1809, `_transform_flows` :1879, `_transform_frequency` :1910, `_transform_numeric_bucket` :1943, `_transform_numeric_sum` :1977, `_transform_numeric_average` :2012) | the S10/S11 smoke-patch surface — BYTE-FIDELITY on conversion math: step-N rate `count/prev_count` with `prev_count>0` guard else `0.0`, overall `steps[-1].count / steps[0].count` else `0.0` (`live_query.py:135-147`); empty-cohort retention `0.0` (`_transform_retention`/`_transform_retention_result`, `:159-221`, `:537-674`); segmented `$overall` selection (`:101-104` docstring + `_extract_steps_from_date_data`) |
| `workspace.py` S2 members | segmentation :1583, funnel :1618, retention :1650, event_counts :1694, property_counts :1726, activity_feed :1767, query_saved_report :1846, query_saved_flows :1882, frequency :1900, segmentation_numeric :1935, segmentation_sum :1973, segmentation_average :2008; `_build_query_params` :2047-2283; query :2285, build_params :2431, `_resolve_and_build_params` :2546, `_build_funnel_params` :2746, `_resolve_and_build_funnel_params` :2930, query_funnel :3064, build_funnel_params :3202, `_build_retention_params` :3321, `_build_flow_params` :3493, `_resolve_and_build_flow_params` :3635, query_flow :3852, build_flow_params :3988, `_resolve_and_build_retention_params` :4100, query_retention :4225, build_retention_params :4349 (ends :4463); query-user engine `_resolve_and_build_user_params` :9336, `_execute_user_query_sequential` :9629, query_user :9722, build_user_params :9883, `_execute_user_aggregate` :10002, `_execute_user_query_parallel` :10069, `_build_page_kwargs` :10209 | current-HEAD def lines (the api-map `lineno` fields are pin-time and have drifted ~20-300 lines — trust these). NOTE: `stream_events` :1400 / `stream_profiles` :1469 / `api` :4465 are **B4 members already ported** (`services/queries/streaming.ts`, client escape hatch) — the skeleton exposes them as thin re-exports ONLY if the B4 standalone functions need a facade veneer for B6; at B5 leave them OUT with a section comment (zero corpus `workspace.stream_*`/`workspace.api` vectors; api-map batch=B4). |

### TS homes

- `packages/core/src/services/live-query.ts` (service class + all transforms;
  split a `live-query-transforms.ts` sibling if >1,500 LOC — R7.2).
- `packages/core/src/workspace.ts` (skeleton §2 + the 22 members).
- Query-user parallel path: Python `ThreadPoolExecutor` (`:10069-10207`)
  ports as bounded-concurrency promise scheduling with the SAME worker-cap,
  page-ordering, early-exit-on-limit, and failed-page semantics —
  `test_workspace_query_user_parallel.py` is the lock (10 classes). Rate-limit
  warning behavior (`TestParallelRateLimitWarning`) keeps Python's
  warn-then-continue shape.
- Delegate map (client methods that ALREADY EXIST, import by name —
  `b4-packets.md:595-603`): LiveQueryService → `segmentation`, `funnel`,
  `retention`, `event_counts`, `property_counts`, `activity_feed`,
  `query_saved_report`, `query_saved_flows`, `frequency`,
  `segmentation_numeric`, `segmentation_sum`, `segmentation_average`,
  `insights_query`, `arb_funnels_query`; query-user engine →
  `export_profiles_page` + `engage_stats` (`workspace.py:9685,9700` +
  `:10048,:10110,:10155` pin-time refs — re-measure at current HEAD).

### api-map rows (PASTED — the contract; `?` params abbreviated in
`ts_signature` are completed by the `params`/`kwonly` lists)

```
workspace.segmentation        params:[event] kwonly:[from_date,to_date,on,unit,where] → SegmentationResult
workspace.funnel              params:[funnel_id] kwonly:[from_date,to_date,unit,on] → FunnelResult
workspace.retention           params:[] kwonly:[born_event,return_event,from_date,to_date,born_where,return_where,interval,interval_count,unit] → RetentionResult
workspace.event_counts        params:[events] kwonly:[from_date,to_date,type,unit] → EventCountsResult
workspace.property_counts     params:[event,property_name] kwonly:[from_date,to_date,type,unit,values,limit] → PropertyCountsResult
workspace.activity_feed       params:[distinct_ids] kwonly:[from_date,to_date,limit,include_events,exclude_events,sentinel_event,paging_window,search,search_properties,use_custom_events] → ActivityFeedResult
workspace.query_saved_report  params:[bookmark_id] kwonly:[bookmark_type,from_date,to_date] → SavedReportResult
workspace.query_saved_flows   params:[bookmark_id] kwonly:[] → FlowsResult
workspace.frequency           params:[] kwonly:[from_date,to_date,unit,addiction_unit,event,where] → FrequencyResult
workspace.segmentation_numeric params:[event] kwonly:[from_date,to_date,on,unit,where,type] → NumericBucketResult
workspace.segmentation_sum    params:[event] kwonly:[from_date,to_date,on,unit,where] → NumericSumResult
workspace.segmentation_average params:[event] kwonly:[from_date,to_date,on,unit,where] → NumericAverageResult
workspace.query               params:[events] kwonly:[from_date,to_date,last,unit,math,math_property,per_user,percentile_value,group_by,where,formula,formula_label,rolling,cumulative,mode,time_comparison,data_group_id] → QueryResult
workspace.build_params        params:[events] kwonly:(same 17 as query) → dict[str, Any]
workspace.query_funnel        params:[steps] kwonly:[conversion_window,conversion_window_unit,order,from_date,to_date,last,unit,math,math_property,group_by,where,exclusions,holding_constant,mode,reentry_mode,time_comparison,data_group_id] → FunnelQueryResult
workspace.build_funnel_params params:[steps] kwonly:(same 17) → dict[str, Any]
workspace.query_flow          params:[event] kwonly:[forward,reverse,from_date,to_date,last,conversion_window,conversion_window_unit,count_type,cardinality,collapse_repeated,hidden_events,mode,where,data_group_id,segments,exclusions] → FlowQueryResult
workspace.build_flow_params   params:[event] kwonly:(same 16) → dict[str, Any]
workspace.query_retention     params:[born_event,return_event] kwonly:[retention_unit,alignment,bucket_sizes,from_date,to_date,last,unit,math,group_by,where,mode,unbounded_mode,retention_cumulative,time_comparison,data_group_id] → RetentionQueryResult
workspace.build_retention_params params:[born_event,return_event] kwonly:(same 15) → dict[str, Any]
workspace.query_user          params:[] kwonly:[where,cohort,properties,sort_by,sort_order,limit,search,distinct_id,distinct_ids,group_id,as_of,mode,aggregate,aggregate_property,percentile,segment_by,parallel,workers,include_all_users] → UserQueryResult
workspace.build_user_params   params:[] kwonly:(same 19, limit-position differs: …,segment_by,limit,parallel,workers,include_all_users) → dict[str, Any]
```

(Full `ts_signature` strings: extract verbatim via
`jq '.workspace_members[] | select(.batch=="B5")' context/typescript-port-api-map.json`
— the S2 builder embeds them as JSDoc.)

### Vectors: 480 (table §1). All five builder families are oracle-callable
(`kind: builder` registry facades, `registry.py:107-114,161-175`); the
wire-kind members (query_saved_report 37, query_saved_flows 6, funnel 3,
retention 3, singles) replay through `workspaceFromSession` (§6).

### Layer-3 translation scope (complete class enumeration, A-F2 style)

TS test home: `packages/core/test/services/` + `packages/core/test/workspace/`
(vitest discovers `packages/*/test/**` only — the B2-M1/M2/M3 recorded
deviation from "colocated `src/`" holds for B5 too).

| Python file (classes at `grep -n '^class '`) | Owner |
|---|---|
| `tests/unit/test_live_query.py` (1240) — TestLiveQueryService :57, TestSegmentation :78, TestFunnel :287, TestExtractStepsFromDateData :528, TestRetention :658, TestEventCounts :845, TestPropertyCounts :1013 | `test/services/live-query.test.ts` (ALL 7) |
| `tests/unit/test_live_query_pbt.py` (555) — TestTransformFunnelProperties :127, TestTransformRetentionProperties :314 | `test/services/live-query.pbt.test.ts` (fast-check, same strategy shapes) |
| `tests/unit/test_live_query_phase008.py` (997) — TestActivityFeedService :68, TestNumericSumService :279, TestNumericAverageService :355, TestFrequencyService :427, TestNumericBucketService :516, TestQuerySavedReportService :597, TestPhase008ServiceErrorHandling :703, TestPhase008EdgeCases :964 | `test/services/live-query-phase008.test.ts` (ALL 8) |
| `tests/unit/test_live_query_flow.py` (495) — TestArbFunnelsQuery :88, TestTransformFlowResult :134, TestQueryFlow :189, TestParseTreeNode :326, TestTransformFlowResultTree :417, TestQueryFlowTree :455 | `test/services/live-query-flow.test.ts` (ALL 6) |
| `tests/unit/test_live_query_bookmarks.py` (350) — TestQueryFlows :15, TestQuerySavedReportNormalization :151 | `test/services/live-query-bookmarks.test.ts` (ALL 2) |
| **B3-deferred** `tests/test_transform_funnel.py` (524) — TestExtractFunnelStepsFromSeries :57, TestTransformFunnelResult :338 | `test/services/transform-funnel.test.ts` (ALL 2; closes the B3-K3 deferral, `B3-K3-notes.md:85-92`) |
| **B3-deferred** `tests/test_transform_retention.py` (613) — TestTransformRetentionBasic :62, TestTransformRetentionErrors :138, TestTransformRetentionNonDictSeries :321, TestTransformRetentionSegments :407, TestTransformRetentionDateNormalization :469, TestTransformRetentionFormatVariations :538 | `test/services/transform-retention.test.ts` (ALL 6) |
| **B2-deferred WHOLE** `tests/test_validation_bypass.py` (414) — TestVector1MetricFilterCPFixed :78, TestVector2FunnelStepFilterCPFixed :138, TestVector3InlineCohortDesignChoice :178, TestVector4WarningOnlyEnumDesignChoice :224, TestVector5NegativeCPRefFixed :270, TestVector6EmptyFormulaFixed :301, TestVector7FormulaShowClauseFixed :340, TestCombinedFixes :383 | `test/workspace/validation-bypass.test.ts` (ALL 8; closes the B2-M2 whole-file deferral, `B2-M2-notes.md:120-132` + `validation-bookmark.test.ts:14-27` header) |
| **B2-deferred WHOLE** `tests/test_validation_bypass_r2.py` (287) — TestR2V1FlowStepFiltersCPFixed :67, TestR2V2RetentionEventFiltersCPFixed :124, TestR2V3NaNFilterFixed :185, TestR2V4InfFilterFixed :223, TestR2CombinedFixes :259 | `test/workspace/validation-bypass-r2.test.ts` (ALL 5) |
| **B2-deferred facade classes** `tests/unit/test_query_validation.py` (827) — the 11 facade-driven classes named in the `query-validation.test.ts:5-15` header (TestTimeRangeValidation :61 raises-cases, TestAggregationValidation :161 raises-cases, TestPerMetricValidation :287, TestFormulaValidation :344 raises-case, TestAnalysisModeValidation :377, TestGroupByValidation :405, TestEmptyEventsValidation :494, TestFormulaInListValidation :521, TestBuildParamsValidation :558, TestPercentileValidation :586, TestHistogramValidation :622) | `test/workspace/query-validation-facade.test.ts` (validator-direct halves already at B2 — do NOT re-translate those asserts; TestValidateTimeArgs :658 / TestValidateGroupByArgs :743 fully translated at B2, header exclusion) |
| `tests/unit/test_query_params.py` (1699) — TestBasicParams :49, TestAggregationParams :214, TestFilterParams :330, TestGroupParams :478, TestMultiEventParams :610, TestFormulaParams :687, TestAnalysisModeParams :766, TestModeParams :837, TestPerMetricFilters :906, TestGroupByTypeError :975, TestFiltersCombinatorParams :1007, TestFormulaObjectParams :1089, TestBuildParams :1199, TestDateFilterParams :1253, TestMultiFormulaParams :1320, TestPercentileParams :1376, TestHistogramParams :1422, TestNewMathTypesInBuildParams :1458, TestSegmentMethodInBuildParams :1502, TestFrequencyBreakdownInBuildParams :1539, TestFrequencyFilterInBuildParams :1599, TestDataGroupIdInsights :1647 | `test/workspace/query-params.test.ts` (ALL 22; R10.7 frequency-filter bug-compat per the probe doc — see Cautions #6) |
| `tests/unit/test_query_integration.py` (444) — TestQueryTimeseries :109, TestQueryNonExistentEvent :191, TestMultiEventIntegration :233, TestFormulaIntegration :266, TestTotalModeIntegration :290, TestQueryPersistence :310, TestTransformQueryResultValidation :330, TestFormulaInListIntegration :374, TestBuildParamsNoApiCall :430 | `test/workspace/query-integration.test.ts` (ALL 9) |
| `tests/test_build_funnel_params.py` (879) — 11 classes :68-:868 (Defaults, Configuration, PublicMethod, PerStepFilters, GlobalFilterGroupBy, MixedSteps, Exclusions, HoldingConstant, NewMathTypes, ReentryMode, TestDataGroupIdFunnel) | `test/workspace/build-funnel-params.test.ts` (ALL 11) |
| `tests/test_build_retention_params.py` (455) — 10 classes :65-:444 | `test/workspace/build-retention-params.test.ts` (ALL 10) |
| `tests/test_build_cohort_params.py` (1034) — TestBuildFilterEntryCohort :94, TestBuildFilterSectionMixed :171, TestBuildFlowCohortFilter :206, TestBuildGroupSectionCohort :255, TestBuildGroupSectionMixed :344, TestBuildParamsCohortFilter :375, TestBuildFunnelParamsCohortFilter :399, TestBuildRetentionParamsCohortFilter :426, TestBuildParamsCohortBreakdown :455, TestBuildFunnelParamsCohortBreakdown :481, TestBuildRetentionParamsCohortBreakdown :507, TestBuildParamsCohortMetric :546, TestBuildParamsCohortMetricMixed :621, TestBuildParamsCohortMetricMathIgnored :663, TestQueryFlowCohortFilter :791, TestBuildFlowCohortFilterDirect :841, TestCodedFlowCohortFilterCodes :927 | `test/workspace/build-cohort-params.test.ts` (ALL 17; the builder-direct classes :94-:344 + :841-:927 assert B3 functions through the facade path — keep facade-driven; B3-K2's corpus-mirror describe block is additive, never a substitute, `B3-K2-notes.md:125-128`) |
| `tests/test_workspace_funnel.py` (466) — TestQueryFunnelValidation :108, TestQueryFunnelExecution :233, TestBuildFunnelParamsVsQueryFunnel :381 | `test/workspace/workspace-funnel.test.ts` (ALL 3) |
| `tests/test_workspace_retention.py` (336) — TestQueryRetentionIntegration :105, TestQueryRetentionWithFilters :219, TestBuildRetentionParams :252, TestQueryRetentionValidationIntegration :319 | `test/workspace/workspace-retention.test.ts` (ALL 4) |
| `tests/unit/test_workspace_flow.py` (1247; NOTE: playbook row says `tests/test_workspace_flow.py` — the file lives under `tests/unit/`) — TestBuildFlowParams :77, TestBuildFlowParamsFilters :360, TestWorkspaceFlowPublicMethods :490, TestMultiStepNormalization :605, TestMultiStepAnchorPosition :759, TestPerStepDirectionValidation :781, TestFlowStepDatetimeFilters :846, TestQueryFlowTreeIntegration :937, TestDataGroupIdFlow :991, TestFlowSessionEvent :1018, TestFlowSegments :1065, TestFlowExclusions :1130, TestFlowPropertyFilters :1176 | `test/workspace/workspace-flow.test.ts` (ALL 13) |
| `tests/test_workspace_cohort.py` (412) — TestQueryFlowWhere :114, TestResolveAndBuildParamsCohortMetric :250 | `test/workspace/workspace-cohort.test.ts` (ALL 2) |
| `tests/test_custom_property_query.py` (298) — TestGroupByCustomPropertyE2E :62, TestFilterCustomPropertyE2E :124, TestMeasurementCustomPropertyE2E :158, TestCombinedPositions :209, TestListCustomPropertiesErrorHandling :260 | `test/workspace/custom-property-query.test.ts` (ALL 5; ListCustomPropertiesErrorHandling drives the B4 client method — translate against it) |
| `tests/test_custom_property_types.py` (515) — TestPropertyInput :50, TestInlineCustomProperty :101, TestInlineCustomPropertyNumeric :140, TestCustomPropertyRef :173, TestImmutability :194, TestTypeWidening :227, TestCustomPropertyValidationCP1 :304 … CP6 :419, TestCustomPropertyValidationValid :436, …FilterPosition :457, …MeasurementPosition :469, …FunnelRetention :480 | `test/workspace/custom-property-types.test.ts` (CP1-CP6 + Valid/Position classes drive `ws.build_params` — S2 proper; the type-construction classes :50-:227 translate here too UNLESS an assert is already locked verbatim by a Phase-2 types test — then a header exclusion citing the exact phase-2 file:line) |
| **B3-deferred** `tests/test_custom_property_builders.py::TestMeasurementPropertyBuilder` :361 (other 3 classes translated at B3-K2) | append to `test/workspace/custom-property-query.test.ts` (closes `B3-K2-notes.md:123`) |
| **B3-deferred** `tests/unit/test_bookmark_builders_pbt.py::TestTimeSectionEquivalence`/`TestFilterSectionEquivalence`/`TestGroupSectionEquivalence` (assert `ws._build_query_params(...) == build_*(...)` — facade wiring) | `test/workspace/build-params-equivalence.pbt.test.ts` (closes `B3-K2-notes.md:120-122`) |
| `tests/test_workspace_build_user_params.py` (825) — 13 classes :113-:740 (FilterTranslation, CohortRouting, PropertySelection, SortByTranslation, AsOfConversion, DistinctIdHandling, GroupIdTranslation, SearchPassthrough, RawStringWhere, ValidationErrors, AggregateModeParams, ModeSpecificValidation, CombinedScenarios) | `test/workspace/build-user-params.test.ts` (ALL 13) |
| `tests/test_workspace_query_user.py` (1379) — 18 classes :164-:1355 | `test/workspace/query-user.test.ts` (ALL 18; pandas `.df` asserts → `toRows()` per C6) |
| `tests/test_workspace_query_user_aggregate.py` (1217) — 14 classes :121-:1123 | `test/workspace/query-user-aggregate.test.ts` (ALL 14) |
| `tests/test_workspace_query_user_integration.py` (1141) — 11 classes :182-:1116 | `test/workspace/query-user-integration.test.ts` (ALL 11) |
| `tests/test_workspace_query_user_parallel.py` (1426) — 10 classes :239-:1291 | `test/workspace/query-user-parallel.test.ts` (ALL 10; fake timers + injected scheduling, W-F6 pattern) |
| `tests/test_query_user_edge_cases.py` (999) — TestTier1DataCorruption :173, TestTier2CrashPaths :593, TestTier3ValidationGaps :768 | `test/workspace/query-user-edge-cases.test.ts` (ALL 3; the B3-K4 note routed the FILE here, `B3-K4-notes.md:86-87`) |
| `tests/test_query_user_structural.py` (625) — remaining 8 classes: TestParallelPageOrderingPreserved :171, TestParallelLimit1FallsBackToSequential :241, TestParallelPageSizeZeroFallback :274, TestParallelPageSizeNoneFallback :307, TestAggregateComputedAtFromAPI :347, TestAggregateComputedAtFallback :375, TestCrossEngine-style df classes TestDfProfilesVaryingPropertySetsUnionColumns :526, TestDfPropertyNamedDistinctIdCollision :585 | `test/workspace/query-user-structural.test.ts` (8 of 12; TestPbtFormatValueSpecialChars :416 + TestFiltersToSelectorOrAndPrecedence :461 translated at B3-K4, TestTransformProfileMissingDistinctId :492 + TestTransformProfileCompletelyEmpty :509 at B3-K3 — header exclusions citing `B3-K3-notes.md:93-96` / `B3-K4-notes.md:87-90`) |
| `tests/unit/test_query_workspace_scoping.py` — TestWorkspaceFacadeScoping :379 | `test/workspace/facade-scoping.test.ts` (the B4-C1 header exclusion routed it here, `b4-packets.md:437`). TestDiscoveryCacheAcrossUse :401 → **B6-W1** (depends on `use()`; header-cited deferral). Client classes :128-:324 were B4. |
| `bookmarks/test_query_validation.jsonl`-only classes | (no extra file — the 10 vectors replay at (b′)) |

Also close at S2: `types/results/query-engine.ts:831` + `:1170` TODO(port)
(anytree/networkx flow surfaces): implement `FlowTreeNode.toAnytree()`-
equivalent as a PLAIN nested-object tree and `FlowQueryResult.graph` as a
plain adjacency object (nodes/edges arrays mirroring what Python feeds
networkx); codec-visible `_graph_cache`/`_anytree_cache` slots STAY null
(codec surface unchanged). Layer-3 asserts that require networkx/anytree
API specifically get header-cited exclusions.

### R10.10 consumers (S2)

- Measured: **zero B6 members** call the S2 private helpers
  (`_resolve_and_build_*`/`_build_query_params` grep 2026-08-16 confined to
  the S2 ranges). Consumers are end users + the corpus + the S3
  `ReplaysService.discover/events_for` `query_fn` seam (bound `query`
  member — S3 depends on S2's skeleton).
- B2 validators (`validation-args.ts` etc.) and B3 builders
  (`bookmarks/builders.ts`, `query/user-builders.ts`, `segfilter.ts`,
  `transforms.ts`) are imported BY NAME — the b2/b3 packets' call-site rows
  (`b2-packets.md` §R10.10 V1a: `workspace.query` → `validate_query_args` +
  `validate_bookmark`; funnel/flow/retention twins) are the wiring spec.
  R10.12 (new-format `filterValue` JSON numbers) and R10.11 (operand
  rendering) apply verbatim.
- `patchCustomPropertyFiltersForTransform` must be called where Python
  patches CP filters pre-transform (`B3-K2-notes.md:175`).

### R10.9 harness spec (S2) — `throwaway/b5-s2/`

- Mandatory edge set (18.0, 1.5, True, None, [], "", "𝒳") through EVERY
  oracle family the shard owns: `workspace.build_params`,
  `workspace.build_funnel_params`, `workspace.build_flow_params`,
  `workspace.build_retention_params`, `workspace.build_user_params` —
  ≥500 examples/family, annotation-constrained domains (Discrepancy #8),
  integer-like unknown params keys excluded (#9/#10 pattern).
- **Transform math edge cases (mandated by the batch ground state)**, via
  canned `VectorFetch` responses through the wire members: zero-denominator
  funnel (`steps[0].count == 0` → overall 0.0; `prev_count == 0` → step rate
  0.0, `live_query.py:135-147`), single-step funnel, empty-steps funnel,
  empty-cohort retention (all-zero cohort → rates 0.0), mixed
  empty/live cohorts, segmented `$overall` funnels, `$overall`-absent
  segmented shape, non-dict retention series, cohort-date normalization
  (`_normalize_cohort_date` :498), integral-float counts (18.0) through
  parseLossless.
- Every error branch: the V*/B*/U* registry codes reachable from the 22
  members (enumerate from `errors-codes.gen.ts` families the B2/B3 modules
  raise) + `BookmarkValidationError` aggregation paths.
- Wire members (query_saved_report/query_saved_flows/funnel/retention/…):
  no oracle surface — edge set replayed through `VectorFetch` with
  hand-built interactions covering every consumed status branch.
- RUN record (counts, seeds, divergence table) → `context/phase3/notes/B5-S2-notes.md`.

### Done-criteria (S2)

`tsc --strict` clean · translated suites green · the 480 S2 vectors PASS
once (b′) lands (426 builder-kind via oracle bindings; 54 wire-kind via
`workspaceFromSession`) · skeleton section markers in place · R10.9 RUN
record · one TS commit (+ Python commit only if notes land separately).

---

## §4 Packet S1 — DiscoveryService + lexicon schemas + schema graph + 12 facade members (opus)

### Scope / Python sources

| Source | Ranges |
|---|---|
| `_internal/services/discovery.py` (920) | helpers `:1-358` (incl. `_is_iso_date`-family `:175-232`); `class DiscoveryService` `:359-920` — `__init__` :393 (in-memory lifetime cache `_cache` :401 + `_schema_graph_cache` :403; NO TTL; `list_top_events` deliberately uncached :375), list_events :405, list_properties :458, `_find_similar_events` :495, list_subproperties :543, list_property_values :587, list_funnels :624, list_cohorts :649, list_bookmarks :684, list_top_events :719, clear_cache :751, list_schemas :765, get_schema :800, get_schema_graph :833 (clock site :889 — `now` seam, §0.4) |
| `workspace.py` S1 members | events :1039, properties :1090, property_values :1106, subproperties :1132, funnels :1193, cohorts :1206, list_bookmarks :1219, top_events :1243, clear_discovery_cache :1273, lexicon_schemas :1285, lexicon_schema :1315, schema_graph :1346 (section ends :1398) |

### TS homes

`packages/core/src/services/discovery.ts` (service + lexicon parsing +
graph assembly) + the S1 member section of `workspace.ts`. Closes the
`types/results/discovery.ts:1083` TODO(port): implement
`SchemaGraphResult.toGraph()` as a plain adjacency object (node list with
attrs + edge list with density attrs — exactly the sets Python hands
networkx); `_graph_cache` codec slot stays null. Delegate map (B4 client
methods, import by name — `b4-packets.md:595-599`, `:875-877`):
`list_events→get_events`, `list_properties→get_event_properties`,
`list_property_values→get_property_values`, `list_top_events→get_top_events`,
`list_funnels→list_funnels`, `list_cohorts→list_cohorts`,
`list_bookmarks→list_bookmarks`, `list_subproperties→get_event_properties`+
sampling, `list_schemas/get_schema→get_schemas/get_schema`,
`get_schema_graph→` bulk lexicon calls (`list_event_definitions`,
`list_property_definitions`).

### api-map rows (PASTED)

```
workspace.events                params:[] kwonly:[limit,from_date,to_date] → list[str]
workspace.properties            params:[event] kwonly:[] → list[str]
workspace.property_values       params:[property_name] kwonly:[event,limit] → list[str]
workspace.subproperties         params:[property_name] kwonly:[event,sample_size] → list[SubPropertyInfo]
workspace.funnels               params:[] kwonly:[] → list[FunnelInfo]
workspace.cohorts               params:[] kwonly:[] → list[SavedCohort]
workspace.list_bookmarks        params:[bookmark_type] kwonly:[] → list[BookmarkInfo]
workspace.top_events            params:[] kwonly:[type,limit] → list[TopEvent]
workspace.clear_discovery_cache params:[] kwonly:[] → void   (wire_state registry kind)
workspace.lexicon_schemas       params:[] kwonly:[entity_type] → list[LexiconSchema]
workspace.lexicon_schema        params:[entity_type,name] kwonly:[] → LexiconSchema
workspace.schema_graph          params:[] kwonly:[include_density,include_user_properties,force_refresh] → SchemaGraphResult
```

### Vectors: 0 (measured — no corpus vector carries an S1 member name).
The contract locks are Layer-3 + the flip-safety of the 12 exact-name
entries at the gate (all flip `done` with zero vectors — legal; stragglers
would surface as FAIL_ERROR if any re-pin ever adds vectors).

### Layer-3 translation scope (complete class enumeration)

| Python file (classes) | Owner |
|---|---|
| `tests/unit/test_discovery.py` (1443) — TestDiscoveryService :62, TestListEvents :95, TestListProperties :236, TestFindSimilarEvents :360, TestListPropertyValues :465, TestClearCache :580, TestListFunnels :661, TestListCohorts :759, TestListTopEvents :930, TestListSubproperties :1080 | `test/services/discovery.test.ts` (ALL 10) |
| `tests/unit/test_discovery_pbt.py` (716) — TestParseLexiconMetadataProperties :293, TestParseLexiconPropertyProperties :388, TestParseLexiconSchemaProperties :457, TestParseBookmarkInfoProperties :526, TestInferSubpropertiesInvariants :623 | `test/services/discovery.pbt.test.ts` (ALL 5, fast-check) |
| `tests/unit/test_discovery_bookmarks.py` (307) — TestListBookmarks :28 | `test/services/discovery-bookmarks.test.ts` |
| `tests/unit/test_lexicon_schemas.py` (719) — TestEndpointsApp :44, TestParseLexiconMetadata :68, TestParseLexiconProperty :121, TestParseLexiconDefinition :157, TestParseLexiconSchema :199, TestLexiconMetadata :241, TestLexiconProperty :281, TestLexiconDefinition :307, TestLexiconSchema :333, TestAPIClientGetSchemas :401, TestAPIClientGetSchema :467, TestDiscoveryServiceListSchemas :533, TestDiscoveryServiceGetSchema :644 | `test/services/lexicon-schemas.test.ts` (ALL 13 — incl. the three client-direct classes TestEndpointsApp/TestAPIClientGetSchemas/TestAPIClientGetSchema: B4-C5's scope did NOT take this file (`b4-packets.md:862-870`), and the app-endpoint rows are un-asserted in `client/url.test.ts` — they translate HERE against the B0/B4 exports; type classes :241-:333 vs any Phase-2 coverage: same rule as §3 custom-property types) |
| `tests/unit/test_schema_graph.py` (539) — TestSchemaGraphResult :69, TestApiClientBulkLexicon :274, TestCanonicalResourceType :378, TestDiscoveryGetSchemaGraph :398, TestFacadeAndCli :504 | `test/services/schema-graph.test.ts` — TestApiClientBulkLexicon (client-direct, translate against B4 client), TestCanonicalResourceType, TestDiscoveryGetSchemaGraph, TestFacadeAndCli **facade half** (CLI half: header exclusion — the CLI is out of Phase-3 scope, api-map preamble). TestSchemaGraphResult: translated in Phase 2 (`test/types/results/schema-graph.test.ts:1-11`) — header exclusion EXCEPT the `to_graph()` asserts, which come alive with `toGraph()` and translate here. |

### R10.10 consumers (S1)

`ReplaysService.discover` consumes discovery-free paths (query_fn only) —
none. B6-W1 `use()` must RESET the discovery cache exactly as Python's
facade does across `use` (the deferred `TestDiscoveryCacheAcrossUse` is
B6's lock — S1's cache must expose the reset hook it will need: `clearCache()`
public on the service, mirroring `clear_cache` :751).

### R10.9 harness spec (S1) — `throwaway/b5-s1/`

No oracle families (wire-kind, exempt). Reduce to the edge set through
`VectorFetch` canned responses per member: empty lists, non-BMP event names
("𝒳"), integral-float counts (18.0) through parseLossless, similar-events
suggestion path (`_find_similar_events` :495 — difflib parity: the B2
Cautions §difflib precedent applies if cutoffs are shared), cache
hit/miss/clear sequences (call twice, one fetch), `list_top_events`
uncached (two fetches), schema-graph density on/off + `force_refresh`,
every error branch reachable through the delegates (canned 4xx/5xx via the
B4 client's `_handle_response` — assert code passthrough, not re-handling).

### Done-criteria (S1)

`tsc --strict` clean · all 5 suites green · `toGraph()` TODO closed ·
member section appended without touching S2/S3 sections · RUN record in
`B5-S1-notes.md` · commit.

---

## §5 Packet S3 — ReplaysService + rrweb analyzer + aggregators + replay_labels + 10 replay members (opus)

### Scope / Python sources

| Source | Ranges |
|---|---|
| `_internal/services/replays.py` (971) | `_looks_like_rrweb` :70, `replay_not_found_error` :91, `class ReplaysService` :125 (`__init__` :150 — DI: api_client + `query_fn` + logger + `_async_transport` seam), sign :178 (clock :207), fetch_files :224, **walk_cdn_async :277-396** (batch loop, 403 re-sign-once, first-file-404 → ReplayNotFoundError, mid-walk 404 sentinel → clean stop, per-file `sorted(events, key=int(timestamp))` yield :392-393), `_fetch_batch` :396 (asyncio.gather in file-num order), `_fetch_one` :420 (URL `{url}{file_num:04d}-{retention_days}.json?{query_string}` :453; credential-redaction on transport errors :455-467; 200→parseLossless list-else-[] :464-471; 403/404 → sentinel tuple :472-473; other → `CDN_UNEXPECTED_STATUS` :474-478), `_build_expired_error` :480, discover :508, `_parse_summaries` :597, events_for :670; module tail transforms `:786-971` |
| `_internal/replays/rrweb_analyzer.py` (969) | IntEnums :52-93 (§0.6); PageVisit :94, ConsoleError :107, AnalyzerResult :122, `_selector_attrs` :145, DOMTracker :168-518, EventAnalyzer :519-819, `_collapse_timeline` :820, MarkdownReporter :849, RrwebAnalyzer :874, `analyze_events` :924, `_render_markdown` :952 — pure stdlib, port whole |
| `_internal/replays/aggregators.py` (172) | real_clicks :26, top_clicks :52, rage_clicks :80, long_pauses :132, error_sessions :158 — pandas surfaces → row-array twins (C6 `toRows()` precedent) |
| `replay_labels.py` (145) | url_normalizer :39, default_label_fn :86, selector_label_fn :114 (closure factory :137) — public exports (the three phase2-audit A1 deferrals owned by B5) |
| `workspace.py` S3 members | list_replays :10679, events_for_replay :10757, events_for_replays :10795, sign_replay :10832, sign_replays :10854, fetch_replay :10875 (analyzer runs at THIS layer — `replays.py:129-133` docstring), stream_replay :10983 (iterator — R6.6), fetch_replays :11045, replays_for_user :11186, analyze_replay :11251, `_resolve_retention` :11275 |
| `types.py` ReplayBundle/Replay TODO closure | summary_markdown :13188 (Replay) / :13858 (Bundle), elements_df :13513, find_pattern :13718, sample :13808 (see decision below), join_mixpanel_events :13835, compare :13888 |

### TS homes

`packages/core/src/replays/` (replaces the placeholder `index.ts`):
`rrweb-analyzer.ts`, `aggregators.ts`, `replay-labels.ts` (public re-export
from `packages/core/src/index.ts` — closes the three A1 deferrals);
`packages/core/src/services/replays.ts` (service); the S3 member section of
`workspace.ts`; the ReplayBundle/Replay method additions in
`types/results/replays.ts` (closing its `:15-21` TODO block — cache slots
stay codec-null).

### R6.4 CDN-walker fidelity (the batch-critical rules)

- **Concurrency identical**: batch = `[file_num, min(file_num+concurrency,
  max_files))`; fetches ISSUED in file-number order (TS `Promise.all` over
  an eagerly-constructed array — matches `asyncio.gather` task order;
  `VectorFetch` positional serving stays deterministic because every fetch
  call fires synchronously before the first await).
- **403 semantics**: ANY 403 in batch → if `re_sign_on_expiry` and not yet
  re-signed: re-sign ONCE via `sign([replay_id])`, refetch WHOLE batch; a
  second 403 (or disabled/exhausted) → `SignedURLExpiredError` built from
  the ORIGINAL `signed` (`_build_expired_error(signed)` — note :349/:355
  pass the original, not `current_signed`).
- **404 sentinel**: walk results in file-number order; 404 at absolute file
  0 → `replay_not_found_error`; 404 later → terminate at that index, yield
  the survivors BEFORE it, then return.
- **Mobile check** once on the very first yielded-file's first event
  (`_looks_like_rrweb` :70) → `UnsupportedReplayFormatError`.
- **Credential hygiene**: `query_string` is a bearer credential — scrub it
  from transport-error messages (`:455-467` `<redacted>` replacement) and
  never log the URL. The 8 `replays.fetch_files` vectors lock the error
  shapes (`SIGNED_URL_EXPIRED` details `{expired_at, replay_id, signed_at,
  status_code}`, redaction, max_files bound, file naming, sorted yield).
- **unordered_group**: measured — ZERO replays vectors carry
  `unordered_group` at this pin (interactions are seq-ordered); the keyed
  replay capability exists in `createVectorFetch` (wirestub-locked) and the
  binding must NOT special-case it. If a future re-pin records true
  interleaving, the vectors arrive keyed and replay unchanged.
- CDN fetch uses the SAME injected fetch seam (R2.4) — bindings pass
  `harness.fetch`; timeout ports `_CDN_TIMEOUT` with the D-B4ARB-1
  streaming-body scope (`b4-review-resolution.md` §W-F2).

### api-map rows (PASTED)

```
workspace.list_replays       params:[] kwonly:[distinct_id,replay_ids,from_date,to_date,limit] → list[ReplaySummary]
workspace.events_for_replay  params:[replay_id] kwonly:[event_properties,from_date,to_date] → list[ReplayEvent]
workspace.events_for_replays params:[replay_ids] kwonly:[event_properties,from_date,to_date] → dict[str, list[ReplayEvent]]
workspace.sign_replay        params:[replay_id] kwonly:[env] → SignedReplay
workspace.sign_replays       params:[replay_ids] kwonly:[env] → list[SignedReplay]
workspace.fetch_replay       params:[replay_id] kwonly:[distinct_id,env,retention_days,max_files,include_mixpanel_events,event_properties,cdn_concurrency] → Replay
workspace.stream_replay      params:[replay_id] kwonly:[env,retention_days,max_files,re_sign_on_expiry,cdn_concurrency] → AsyncIterable<dict[str,Any]>  (iterator)
workspace.fetch_replays      params:[replay_ids] kwonly:[env,max_files,include_mixpanel_events,event_properties,concurrency,cdn_concurrency,retention_by_id,distinct_id_by_id] → ReplayBundle
workspace.replays_for_user   params:[distinct_id] kwonly:[from_date,to_date,limit,include_mixpanel_events,event_properties] → ReplayBundle
workspace.analyze_replay     params:[replay_id] kwonly:[] → str
```

### Vectors: 26 — `replays.fetch_files` 8 (`corpus/replays/test_replays_service.jsonl`),
`replay_labels.url_normalizer` 12 + `replay_labels.default_label_fn` 4
(`corpus/replays/test_replay_bundle.jsonl`), `rrweb_analyzer.analyze` 2
(`corpus/authored/replays/rrweb-seed.jsonl` — incl. the
`authored-sample-replay-001-golden` full-fixture golden and the
empty-stream case; `corpus/replays/test_rrweb_analyzer.jsonl` carries 1 of
the url_normalizer 12). All 10 workspace replay members: 0 vectors
(Layer-3-locked only).

### Golden-file suite (plan Layer-3, `typescript-port-plan.md:351-354`)

- Fixture source: `tests/fixtures/rrweb/sample-replay-001.json` (copy into
  `packages/core/test/replays/fixtures/`) + any samples extractable from
  the READ-ONLY `analytics` repo `iron/replay-embed/__test__/fixtures.ts`.
- Golden generation: a `uv run python` script under
  `conformance/goldens/rrweb/` (Python repo — inside the allowed write
  surface) that runs `analyze_events` + `RrwebAnalyzer.analyze` over each
  fixture and freezes `{actions[], markdown, page_visits, console_errors}`
  as JSON; the TS suite (`test/replays/rrweb-analyzer.golden.test.ts`)
  asserts deep equality. Goldens are committed in BOTH repos (Python:
  generator + outputs; TS: copied outputs) with regeneration headers
  (TS-2 pinned-table precedent).

### `ReplayBundle.sample` decision (S3-D1, decide at implementation, arbiter-visible)

Python: `random.Random(seed).sample(list, k)` (`types.py:13819-13824`).
The only Layer-3 lock is SAME-SEED self-consistency
(`test_replay_bundle.py:448-449`); no vector or oracle family reaches it.
**Packet recommendation**: port CPython parity anyway — MT19937 seeded via
`init_by_array` + CPython `random.sample`'s selection-set algorithm
(~120 LOC, pure), locked by pinned CPython probe outputs (seed=42 and a
small seed/k/n matrix recorded via `uv run python`, committed next to the
goldens). This avoids a sanctioned-deviation filing; if the implementer
finds MT parity disproportionate, STOP and escalate for an arbiter ruling
instead of silently substituting a different PRNG (R10.2-adjacent).

### Layer-3 translation scope (complete class enumeration)

| Python file (classes) | Owner |
|---|---|
| `tests/unit/test_rrweb_analyzer.py` (798) — TestAnalyzeEventsWrapper :162, TestConsoleErrors :199, TestDebouncing :267, TestMouseInteractions :349, TestSelectionEvents :487, TestMutations :536, TestDescriptionFallbacks :620, TestDOMTrackerDirect :708, TestMarkdownReporter :768 | `test/replays/rrweb-analyzer.test.ts` (ALL 9) + the golden suite above |
| `tests/unit/test_replay_bundle.py` (537) — TestUrlNormalizer :97, TestDefaultLabelFn :118, TestSelectorLabelFn :135, TestRrwebAnalyzer :162, TestReplayBundleProjections :260, TestReplayBundleAggregations :325, TestReplayBundleFilters :415, TestAggregatorFunctions :459, TestCodedUserActionCodes :485, TestCodedReplayBundleCodes :513 | `test/replays/replay-labels.test.ts` (:97-:135) + `test/replays/rrweb-analyzer.test.ts` (:162) + `test/replays/aggregators.test.ts` (:325, :459 — pandas asserts → row arrays). **Already translated in Phase 2** (`test/types/results/replays.test.ts:1-21` header): TestReplayBundleProjections, TestReplayBundleFilters, TestCodedUserActionCodes, TestCodedReplayBundleCodes — header exclusions citing that file; the `sample`/`summary_markdown`/`elements_df` asserts excluded THERE come alive HERE with the TODO closure |
| `tests/unit/test_workspace_replays.py` (746) — TestListReplaysValidation :97, TestListReplaysQueryCall :148, TestRetentionWarning :237, TestEventsForReplayValidation :284, TestFetchReplay :317, TestReplaysForUser :432, TestSignReplaysWiring :465, TestEventsForReplaysWindow :493, TestFetchReplaysResilience :522, TestReplaysForUserLimit :560, TestFetchReplaysBatching :578, TestReplaysForUserThreadsRetention :634, TestCodedReplayGuardCodes :664 | `test/workspace/workspace-replays.test.ts` (ALL 13) |
| `tests/unit/_internal/test_replays_service.py` (714) — TestSignWrapping :72, TestFetchFilesHappyPath :143, TestFetchFilesTermination :222, TestFetchFiles403Retry :266, TestFetchFilesCredentialRedaction :336, TestMobileReplayDetection :366, TestDiscoverNoQueryFn :397, TestDiscoverParsing :503, TestEventsForParsing :647 | `test/services/replays-service.test.ts` (ALL 9) |

### R10.10 consumers (S3)

`workspace.fetch_replay`/`fetch_replays`/`replays_for_user` feed
`rrweb_events` through the analyzer when building `Replay` objects
(`replays.py:129-133`); `sign_replays` delegates to the B4 client's
`sign_replays` (`services/entities/replays-signing.ts` — import, R10.8;
the 403 `SESSION_RECORDING_SENSITIVE_DATA` branch lives in B0
`handleResponse`, nothing to re-implement). `Replay*` result classes are
B1/Phase-2 (`types/results/replays.ts`) — extend, don't fork.
`replay_labels` exports are public API (`index.ts`).

### R10.9 harness spec (S3) — `throwaway/b5-s3/`

- Oracle families (builder-kind, both bridges): `replay_labels.url_normalizer`,
  `replay_labels.default_label_fn`, `replay_labels.selector_label_fn`,
  `rrweb_analyzer.analyze` — ≥500 examples each (URL arbitrary biased to
  query/fragment/uuid/id-segment shapes for the normalizer; rrweb event
  streams generated from a small grammar over the four IntEnums, non-BMP
  text nodes included).
- **CDN walker concurrency + 404-sentinel + unordered replay (mandated)**:
  `VectorFetch` hand-built interaction sets — first-file 404; mid-batch 404
  with survivors after it in the SAME batch (assert survivors before the
  sentinel yield, nothing after); 404 exactly at a batch boundary;
  403-then-success re-sign; 403-re-sign-then-403; `re_sign_on_expiry=false`;
  max_files < batch size; non-JSON 200 body (`CDN_INVALID_RESPONSE`);
  unexpected 500 (`CDN_UNEXPECTED_STATUS`); transport error (redaction
  assert — the credential string must NOT appear in message/details);
  concurrency=1 vs 50 equivalence on identical interaction sets.
- Edge set through the walker: empty file (200 `[]`), scalar-JSON file,
  events with float timestamps (18.0 → Python `int()` truncation parity),
  non-BMP strings in events.
- Every error branch: `REPLAY_NOT_FOUND`, `SIGNED_URL_EXPIRED`,
  `UNSUPPORTED_REPLAY_FORMAT`, `CDN_FETCH_ERROR`, `CDN_INVALID_RESPONSE`,
  `CDN_UNEXPECTED_STATUS`, the workspace guard codes
  (`TestCodedReplayGuardCodes`).

### Done-criteria (S3)

`tsc --strict` clean · 4 test files + golden suite green · the 26 vectors
PASS at (b′) · `replay_labels` exported from `index.ts` ·
`types/results/replays.ts` TODO block closed (incl. the S3-D1 outcome
recorded in `B5-S3-notes.md`) · RUN record · commit.

---

## §6 Binding plan (the fable BIND task — P3-2 b′, single task after S-shards)

**Registry names to bind** (in `conformance-runner/src/bindings.ts`
registration modules, one new module e.g. `wire-workspace.ts` +
`replays-bindings.ts`):

1. **All 44 `workspace.<member>` names** (§1 table — including the 30
   zero-vector names: bind them anyway; the gate's oracle probe covers
   builder-kind names and the flip's straggler ratchet needs wire names
   resolvable). The five `build_*params` are **builder-kind** (oracle-callable);
   `clear_discovery_cache` is wire_state; the rest wire_api
   (`registry.py:99-114`).
2. **`workspaceFromSession(context)`** — the facade twin of B4's
   `clientFromSession` (`wire-client.ts:243-283`): builds
   `new Workspace({session: parseAccount(call.workspace_session ??
   call.session)…, client: clientFromSession(context)})`, **memoized in
   `context.state` under ONE well-known key** (`"workspace"`) so
   `call.setup[]` entries and the measured call share the instance
   (P3-5 mandate). Builder-kind vectors carry NO session: mirror
   `conformance/runner/targets.py:33-45` — the synthetic
   `{type: service_account, region: us, project_id: "12345", account_name:
   conformance_replay, username: replay_user, secret: replay_secret}`
   session + an EMPTY `VectorFetch` (any network attempt fails loudly).
3. **Replays-family names (all 9 registered)**: wire —
   `replays.sign`, `replays.fetch_files`, `replays.walk_cdn_async`,
   `replays.discover`, `replays.events_for` (bind to a REAL `ReplaysService`
   over `clientFromSession` + `harness.fetch` as the CDN seam, mirroring
   `targets.py:331-346`; only `fetch_files` has vectors today — bind all
   five for the straggler ratchet); builder — `replay_labels.url_normalizer`,
   `replay_labels.default_label_fn`, `replay_labels.selector_label_fn`,
   `rrweb_analyzer.analyze` (+ oracle-ts registration for these four AND
   the five `workspace.build_*params`).
4. **Binding honesty (P3-5 rule 3)**: every binding calls the REAL facade
   member / service method the recorder wrapped — never the underlying
   client method, never a re-derived transform. Arbiter verifies per shard.
5. **`CoreLibraryError.toExpectError()` extension** (B2-BIND forward note,
   `B2-BIND-notes.md:129-131`): add `errors[]` emission for
   `BookmarkValidationError` so the bypass/build vectors' `expect.error`
   comparisons see the V*/B* triples.
6. **Oracle strategies** (`conformance/differential/strategies.py`, Python
   repo — fable rig change, same commit series): add the five
   `workspace.build_*params` families (annotation-constrained per
   Discrepancy #8; integer-like unknown keys excluded per #9/#10) + the
   four replay builder families. Oracle-py already resolves all names via
   the registry; verify with the gate's mechanical probe (one `oracle.call`
   per builder-kind name on BOTH bridges; wire names exempt).
7. **UNPORTED-probe re-anchor** (the B3-BIND/B4-C3 churn convention,
   `B3-BIND-notes.md:76-84`, `B4-C3-notes.md:88-93`): both
   `conformance-runner/test/runner.test.ts` and
   `differential/test/oracle-protocol.test.ts` currently anchor their
   UNPORTED exemplars to `workspace.build_params` / `pagination.paginate_all`
   — post-B5-flip those are PASS/done; re-anchor to a **B6** name
   (recommend `workspace.me` — pending until B6 by construction), comments
   updated in place.
8. **workspace.me ownership decision (the P3-1 † dagger)**: the api-map says
   `me` is **batch B6** (`/ME & PROJECT DISCOVERY`). **Decision: B6-owned —
   NOT bound at B5.** The carried vector
   (`api_client.resolve_workspace_id` × `workspace.me` setup) keeps its
   holdback: UNPORTED at the B5 gate, first PASS at B6 (gate delta 354
   there). No B5 shard implements or binds `me`.

Vector failures surfaced at (b′) are the owning MODULE task's attempt-1
failure (escalation: retry once on fable with context; two misses abort).

---

## §7 Gate flip spec (fable gate task — P3-2 e)

1. `batch-status.ts` changes, ONE commit with the checkpoint:
   - **44 exact-name entries** `workspace.<member>` → `done`, generated
     mechanically: `jq -r '.workspace_members[] | select(.batch=="B5") |
     "workspace." + .name' context/typescript-port-api-map.json`. Generated
     list (verify against a fresh jq run): activity_feed, analyze_replay,
     build_flow_params, build_funnel_params, build_params,
     build_retention_params, build_user_params, clear_discovery_cache,
     cohorts, event_counts, events, events_for_replay, events_for_replays,
     fetch_replay, fetch_replays, frequency, funnel, funnels,
     lexicon_schema, lexicon_schemas, list_bookmarks, list_replays,
     properties, property_counts, property_values, query, query_flow,
     query_funnel, query_retention, query_saved_flows, query_saved_report,
     query_user, replays_for_user, retention, schema_graph, segmentation,
     segmentation_average, segmentation_numeric, segmentation_sum,
     sign_replay, sign_replays, stream_replay, subproperties, top_events.
   - Prefixes `replays.` + `replay_labels.` + `rrweb_analyzer.` → `done`.
   - **The pending override ADDED at this gate**: `workspace.list_bookmarks_v2`
     → `pending` (longer entry wins longest-prefix; without it the B5 entry
     `workspace.list_bookmarks` — zero vectors — flips the 7 unported B6
     `list_bookmarks_v2` vectors to FAIL_ERROR; playbook `:653-659`,
     `B4-notes.md:45`). **Removed at B6** when the whole `workspace.` prefix
     collapses to `done` (playbook `:660-662`).
   - **Standing collision assertion** re-run after generating the 44
     (playbook `:635-639`): scan all still-pending corpus api names for
     `startsWith` hits on the new entries. Measured 2026-08-16: the only
     CROSS-BATCH hit is `workspace.list_bookmarks` → `workspace.list_bookmarks_v2`
     (resolved by the override); `workspace.query` / `workspace.segmentation`
     prefix-capture only same-batch B5 names (`query_saved_*`,
     `segmentation_{sum,numeric,average}` — all flipping `done` together,
     harmless).
   - Batch-status unit suite (full-corpus prefix coverage) stays green.
2. Conformance checkpoint: `npm run conformance` → expect exactly
   **2,876 PASS / 0 FAIL / 375 UNPORTED** (gate delta 506; the † carried
   vector stays UNPORTED — §6.8). Archive report JSON →
   `context/phase3/reports/2026-08-16-b5-gate.json` (or day-of); commit both
   repos.
3. Oracle probe: one `oracle.call` per newly registered **builder-kind** api
   on BOTH bridges (5 `workspace.build_*params` + 3 `replay_labels.*` +
   `rrweb_analyzer.analyze`); wire names exempt. Then the differential
   full-suite regression (cumulative surface, fresh seeds, ≥500/family) —
   zero unexplained divergences; RUN record appended to
   `differential/oracle/RUN.md`.
4. **Referees**: P3-7 schedules referees at B3/B6, with the clause "if a B5
   module emits a bookmark payload anyway, its gate adds the referees" —
   S2's `build_params` EMITS insights bookmark params, so this gate ADDS
   `workspace.build_params` (insights, as-is) to referee (a)'s `FEED_SLOTS`
   (the D15a data-driven feed rule, `B3-notes.md:65`) and re-runs referees
   (a) ajv + (b) round-trip over the refreshed feed. Known standing REJECTs
   carried from B3 (frequency-filter clause shape, dataGroupId int
   threading — open R10.7 items, `B3-notes.md:63`) are EXPECTED and do not
   block; any NEW reject does.
5. `npm run check` green (TS); `just check` green (Python — goldens/strategy
   commits touch the repo). Remove `throwaway/b5-s*/` after arbiter
   sign-off. Finalize `context/phase3/notes/B5-notes.md`.

---

## §8 Deferral-ledger placement (every inbound item, with source cite)

| Inbound deferral | Placed |
|---|---|
| `tests/test_validation_bypass.py` WHOLE (B2-M2, `B2-M2-notes.md:120-132`) | S2 → `test/workspace/validation-bypass.test.ts` |
| `tests/test_validation_bypass_r2.py` WHOLE (B2-M2) | S2 → `test/workspace/validation-bypass-r2.test.ts` |
| `test_query_validation.py` facade classes (B2-M1, `query-validation.test.ts:5-15`) | S2 → `test/workspace/query-validation-facade.test.ts` |
| `tests/test_query_user_edge_cases.py` file (B2-M3 `:44` + B3-K4 `:86`) | S2 → `test/workspace/query-user-edge-cases.test.ts` |
| `tests/test_transform_funnel.py` + `test_transform_retention.py` (B3-K3, playbook misassignment) | S2 → `test/services/transform-{funnel,retention}.test.ts` |
| `test_query_user_structural.py` remaining 8 classes (B3-K3/K4 splits) | S2 → `test/workspace/query-user-structural.test.ts` |
| `test_custom_property_builders.py::TestMeasurementPropertyBuilder` (B3-K2 `:123`) | S2 → appended to `custom-property-query.test.ts` |
| `test_bookmark_builders_pbt.py` 3 equivalence classes (B3-K2 `:120-122`) | S2 → `build-params-equivalence.pbt.test.ts` |
| `tests/test_build_cohort_params.py` + `tests/unit/test_query_params.py` B5-owned files (B3-K2 `:124-128`) | S2 tables §3 |
| `test_query_workspace_scoping.py` facade classes (B4-C1, `b4-packets.md:437`) | S2 (TestWorkspaceFacadeScoping); TestDiscoveryCacheAcrossUse → **B6-W1** (needs `use()`) — outbound deferral, header-cited |
| `response_validation.py` (playbook B5 row) | ALREADY at B4-C1 (`client/response-validation.ts`) — S1/S2 import |
| `validate_bookmark`/`default_label_fn`/`selector_label_fn`/`url_normalizer` A1 deferrals | `validate_bookmark` done at B2; the three label fns → S3 public exports |
| Phase-2 `TODO(port)` B5 rows: `types/results/replays.ts:15` (bundle methods), `query-engine.ts:831,1170` (anytree/graph), `discovery.ts:1083` (to_graph) | S3 / S2 / S1 respectively (§3-§5) |
| B2-BIND `toExpectError` errors[] extension (`B2-BIND-notes.md:129-131`) | BIND task §6.5 |
| B3 referee feed rule (`B3-notes.md:65`) | Gate §7.4 |
| UNPORTED-probe re-anchor churn (B3-BIND/B4-C3) | BIND task §6.7 |
| `arb_funnels_query` consumer note (`b4-packets.md:145`) | S2 delegate map |
| A-F3 `response-validation.ts:22` TODO owner = **B6** (not B5); `py-dates.ts:14` = B8 | no B5 action (recorded so the arbiter doesn't flag them) |

Outbound deferrals created by B5 (for the B6 packet author):
`TestDiscoveryCacheAcrossUse` → B6-W1; `workspace.me` + facade
`stream_events`/`stream_profiles`/`api` veneer decision → B6-W1; the
`workspace.list_bookmarks_v2` pending override removal → B6 gate;
UNPORTED-probe re-anchor lands on a B6 name → B6 gate re-points or retires it.

---

## §9 Cautions (file:line cited)

1. **Transform byte-fidelity is the smoke surface**: overall rate
   `steps[-1].count / steps[0].count` guard `steps[0].count > 0` else 0.0
   (`live_query.py:145-147`); step rate `1.0` for idx 0, else
   `count/prev_count` guard `prev_count > 0` (`:135`); the six authored
   `workspace.funnel`/`workspace.retention` wire vectors
   (`corpus/authored/{funnels,retention}/live-query-transforms.jsonl`)
   assert the math end-to-end — division stays IEEE double, no rounding.
2. **`$overall` segmented handling** (`live_query.py:100-104` +
   `_extract_steps_from_date_data` :51-79): missing `$overall` vs
   missing-`steps` branches differ — port branch-for-branch.
3. **`int(e.get("timestamp", 0))`** (`replays.py:392`): CPython `int()` on a
   float TRUNCATES toward zero and on a numeric string uses `pythonInt`;
   port with the same coercion ladder, not `Number()`.
4. **`_build_expired_error(signed)` uses the ORIGINAL handle**
   (`replays.py:349,:355`) even after a re-sign — details carry the
   original `signed_at`/`expired_at`.
5. **CDN 200 body**: `payload if isinstance(payload, list) else []`
   (`replays.py:470`) — a 200 dict/scalar is an EMPTY file, not an error;
   parse via parseLossless+pythonConstants (§0.2).
6. **R10.7 bug-compat in `test_query_params.py`**: the frequency-filter
   clause shape is a KNOWN open R10.7 item with pinned referee REJECTs
   (`B3-notes.md:63`, `frequency-filter-probe.md`) — translate the asserts
   as Python behaves TODAY; do not "fix" the shape.
7. **Builder members are sync-shaped in Python but the api-map renders
   `async`** (`ts_signature` `async build_params(...)`): follow the api-map
   (facade methods uniformly async in TS) — the oracle bindings await them.
8. **`build_user_params` kwonly order differs from `query_user`**
   (`limit` sits after `segment_by` — api-map rows §3): options-bag naming
   is identical; only Python-side positional binding differs (irrelevant in
   TS, but the recorder's kwargs replay by NAME — keep names exact).
9. **Discovery cache**: lifetime in-memory dict keyed by tuple
   (`discovery.py:400-403,437-443`), NO TTL; `list_top_events` bypasses it
   (`:375`); `clear_discovery_cache` is wire_state (replays as setup only —
   no return-shape contract).
10. **Do not pre-shape B4 client returns** (`b4-packets.md:1083-1084`):
    result-object construction (SegmentationResult etc.) happens ONLY in
    the S-shards; double-transform fails vectors.
11. **rrweb analyzer sanitization**: `DOMTracker._sanitize_value` (:211) and
    `_selector_attrs` (:145) drop/clip attr values — the golden suite will
    catch drift, but port order of checks verbatim (description fallbacks
    :397-518 are order-sensitive).
12. **`analyze_replay` returns markdown TEXT** (`workspace.py:11251`,
    `→ str`) while `fetch_replay` attaches structured actions — don't
    conflate the two rendering paths (`_render_markdown` :952 vs
    `MarkdownReporter.generate` :856).
13. **Zero-vector members still flip `done`** at the gate — S1's 12 and the
    10 replay members have no corpus lock; their Layer-3 suites are the
    ONLY behavior lock. R10.2 diligence on those files is the review pair's
    top item (risk-register #3).
14. **`workspace.list_bookmarks` (S1, 0 vectors) vs `list_bookmarks_v2`
    (B6, 7 vectors)**: never bind or implement `_v2` at B5; the flip
    override (§7.1) is mandatory in the SAME commit as the 44 entries.
15. **api-map `lineno` drift**: workspace.py has grown ~300 lines past the
    pin — every §3-§5 range above is measured at current HEAD; re-measure
    after any upstream merge (P3-7 trigger 4).

---

## §10 Done-criteria (batch, restated per R10.5)

Per shard: packet §3/§4/§5 done-criteria. Batch: (b′) bindings live + 506
vectors PASS + review pair ×2 + arbiter GO per shard + gate steps §7 all
green (`npm run check`, `just check`, report archived, notes finalized,
throwaway removed, commits local on the correct branches).
