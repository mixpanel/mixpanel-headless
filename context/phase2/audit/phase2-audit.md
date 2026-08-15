# Phase-2 Independent Mini-Audit (P2-10)

**Auditor**: fresh-eyes agent, no prior Phase-2 context; every claim below verified
by re-execution or direct sampling, not by reading packet notes.
**Date**: 2026-08-15
**Audited states**:
- TS repo `mixpanel-headless-ts` @ `d5dd02ca03e88fa3156244ee62d338aac3bcc7e6` (branch `main`, clean tree)
- Python repo @ `2d80135d32e4750ce81d32e59d512d81ca5f8cf4` (branch `ts-port/phase2-contract-support`)
- Corpus snapshot @ `8ae76314a0a6` (loader-verified on every conformance run below)
**Spec of record**: `context/phase2/design/phase2-design.md` (C1–C10) + `review-resolution.md`.

## Verdict summary

| # | Audit item (C10 P2-10 row) | Verdict |
|---|---|---|
| A1 | Export coverage map — 274 distinct `__all__` names, each ported / deferred-with-owner | **PASS** |
| A2 | No weakened/dropped assertions in translated tests | **PASS** |
| A3 | `@internal` discipline vs published `.d.ts` | **PASS** (1 nit) |
| A4 | R3.9/R4.10/R4.11 spot-check on 10 random models | **PASS** (10/10) |
| A5 | C8(b) golden-table completeness vs result-class list AND `model-coverage.json` vs 125 entity models | **PASS** |
| A6 | Guard-order parity on 5 sampled multi-guard constructors | **PASS** (12/12 probes) |
| A7 | All `TODO(port)` triaged | **PASS** |
| A8 | Conformance report counts match the P2-8 checkpoint | **PASS** |
| A9 | Common done-criteria re-execution (tsc strict, packet tests, C8 locks, 42 gate, `npm run check`) | **PASS** |

**Overall: PASS.** No blocking findings. Two informational nits recorded (A3, A1-n1);
neither violates a design criterion.

---

## A1 Export coverage map (274 distinct names)

**Method (re-executable):** `sorted(set(mixpanel_headless.__all__))` on the live
package → 284 raw / **274 distinct** (the 10 duplicated Literal-alias strings key
once, Discrepancy Log #9). Runtime-kind classification by introspection
(`typing.get_origin is Literal`, `issubclass(Enum)`, `issubclass(BaseException)`,
`issubclass(pydantic.BaseModel)`, `dataclasses.is_dataclass`, `__total__` for
TypedDicts). The measured partition **matches the design's ground-truth inventory
exactly**: 37 Literal aliases, 8 Enums, 59 dataclasses, 125 Pydantic models,
28 exceptions, 5 TypedDicts, 5 functions, `PropertySpec`, `BUSINESS_CONTEXT_MAX_CHARS`,
`Workspace`, 3 namespace modules, `Account`.

The TS side was extracted with the TypeScript compiler API
(`checker.getExportsOfModule` on `packages/core/src/index.ts` under the package
tsconfig): **533 export names**. Cross-diff results:

- **All 265 expected-ported names are exported from the core barrel** (274 − 9
  design-deferred). Zero missing.
- **All 9 deferred names carry a Phase-3 owner and do NOT leak into the barrel**:
  `Workspace` → B6; `accounts`/`session`/`targets`/`login_unified` → B7;
  `validate_bookmark` → B2; `default_label_fn`/`selector_label_fn`/`url_normalizer` → B5.
- **No unlisted public API appeared** (Risk #8 check): the 268 extra exports are
  all designed companions — `*Init`/`*Fields`/`*Options` constructor bags, the
  C2 `*_VALUES` runtime tuples, the C4 auth free functions
  (`parseAccount`/`accountAuthHeader`/`isLongLived`/`sessionAuthHeader`/…),
  `Secret`, coerce helpers, NewType aliases (`AccountName`/`ProjectId`/
  `WorkspaceId`/`TargetName`), `auth_types` surface (`ActiveSession`,
  `OAuthTokens`, `OAuthClientInfo`, `TokenResolver`), the pre-existing B0
  `compat` slice, and `CORE_PACKAGE_NAME`. No builder/validator names (no
  B2/B3 scope bleed).

*Nit A1-n1 (informational)*: the classifier initially binned `Account` as
callable — Annotated unions are callable at runtime; hand-corrected to the
design's "Annotated union" bucket. No impact.

### Appendix — full per-name map (grouped by runtime kind; unmarked = ported in Phase 2)

- **Literal aliases (37)** — all ported:
  AccountType, BookmarkType, CohortAggregationType, ConversionWindowUnit,
  CountType, CustomPropertyType, EntityType, FilterDateUnit, FilterOperator,
  FilterPropertyType, FiltersCombinator, FlowAnchorType, FlowChartType,
  FlowConversionWindowUnit, FlowCountType, FlowNodeType, FlowSessionEvent,
  FrequencyFilterOperator, FunnelMathType, FunnelMode, FunnelOrder,
  FunnelReentryMode, HourDayUnit, InsightsMode, MathType, PerUserAggregation,
  QueryTimeUnit, Region, RetentionAlignment, RetentionMathType, RetentionMode,
  RetentionUnboundedMode, SavedReportType, SegmentMethod, TimeComparisonType,
  TimeComparisonUnit, TimeUnit
- **Enum classes (8)** — all ported:
  AlertFrequencyPreset, CustomPropertyResourceType, ExperimentStatus,
  FeatureFlagStatus, FlagContractStatus, PropertyResourceType, ServingMethod,
  WebhookAuthType
- **dataclasses (59)** — all ported:
  ActivityFeedResult, BookmarkInfo, CohortBreakdown, CohortCriteria,
  CohortDefinition, CohortInfo, CohortMetric, CustomPropertyRef,
  EventCountsResult, Exclusion, Filter, FlowQueryResult, FlowStep,
  FlowTreeNode, FlowsResult, Formula, FrequencyBreakdown, FrequencyFilter,
  FrequencyResult, FunnelInfo, FunnelQueryResult, FunnelResult,
  FunnelResultStep, FunnelStep, GroupBy, HoldingConstant,
  InlineCustomProperty, LexiconDefinition, LexiconMetadata, LexiconProperty,
  LexiconSchema, ListItemGroupMode, Metric, NumericAverageResult,
  NumericBucketResult, NumericSumResult, ProfilePageResult,
  PropertyCountsResult, PropertyInput, QueryResult, Replay, ReplayBundle,
  ReplayEvent, ReplaySummary, RetentionEvent, RetentionQueryResult,
  RetentionResult, SavedCohort, SavedReportResult, SchemaGraphResult,
  SegmentationResult, SignedReplay, SubPropertyInfo, TimeComparison, TopEvent,
  UserAction, UserEvent, UserQueryResult, ValidationError
- **Pydantic models (125)** — all ported:
  AccountSummary, AccountTestResult, AlertBookmark, AlertCount, AlertCreator,
  AlertHistoryPagination, AlertHistoryResponse, AlertProject,
  AlertScreenshotResponse, AlertValidation, AlertWorkspace, Annotation,
  AnnotationTag, AnnotationUser, AuditResponse, AuditViolation, BlueprintCard,
  BlueprintConfig, BlueprintFinishParams, BlueprintTemplate, Bookmark,
  BookmarkHistoryPagination, BookmarkHistoryResponse, BookmarkMetadata,
  BulkAnomalyEntry, BulkCreateSchemasParams, BulkCreateSchemasResponse,
  BulkEventUpdate, BulkPatchResult, BulkPropertyUpdate,
  BulkUpdateAnomalyParams, BulkUpdateBookmarkEntry, BulkUpdateCohortEntry,
  BulkUpdateEventsParams, BulkUpdatePropertiesParams, BusinessContext,
  BusinessContextChain, Cohort, CohortCreator, ComposedPropertyValue,
  CreateAlertParams, CreateAnnotationParams, CreateAnnotationTagParams,
  CreateBookmarkParams, CreateCohortParams, CreateCustomEventParams,
  CreateCustomPropertyParams, CreateDashboardParams,
  CreateDeletionRequestParams, CreateDropFilterParams, CreateExperimentParams,
  CreateFeatureFlagParams, CreateRcaDashboardParams, CreateTagParams,
  CreateWebhookParams, CursorPagination, CustomAlert, CustomEvent,
  CustomEventAlternative, CustomProperty, Dashboard, DashboardRow,
  DashboardRowContent, DataVolumeAnomaly, DeleteSchemasResponse, DropFilter,
  DropFilterLimitsResponse, DuplicateExperimentParams, EventDefinition,
  EventDeletionRequest, Experiment, ExperimentConcludeParams,
  ExperimentCreator, ExperimentDecideParams, FeatureFlag, FlagHistoryParams,
  FlagHistoryResponse, FlagLimitsResponse, InitSchemaEnforcementParams,
  LexiconTag, LookupTable, LookupTableUploadUrl, MarkLookupTableReadyParams,
  OAuthBrowserAccount, OAuthLoginResult, OAuthTokenAccount, PaginatedResponse,
  PreviewDeletionFiltersParams, Project, ProjectWebhook, PropertyDefinition,
  PublicWorkspace, RcaSourceData, ReplaceSchemaEnforcementParams,
  SchemaEnforcementConfig, SchemaEntry, ServiceAccount, Session,
  SetTestUsersParams, Target, UpdateAlertParams, UpdateAnnotationParams,
  UpdateAnomalyParams, UpdateBookmarkParams, UpdateCohortParams,
  UpdateCustomPropertyParams, UpdateDashboardParams, UpdateDropFilterParams,
  UpdateEventDefinitionParams, UpdateExperimentParams,
  UpdateFeatureFlagParams, UpdateLookupTableParams,
  UpdatePropertyDefinitionParams, UpdateReportLinkParams,
  UpdateSchemaEnforcementParams, UpdateTagParams, UpdateTextCardParams,
  UpdateWebhookParams, UploadLookupTableParams,
  ValidateAlertsForBookmarkParams, ValidateAlertsForBookmarkResponse,
  WebhookMutationResult, WebhookTestParams, WebhookTestResult, WorkspaceRef
- **exception classes (28)** — all ported:
  APIError, AccountExistsError, AccountInUseError, AccountNotFoundError,
  AuthenticationError, BookmarkValidationError,
  BusinessContextValidationError, ConfigError, DateRangeTooLargeError,
  EventNotFoundError, InvalidArgumentError, MixpanelHeadlessError, OAuthError,
  ParamTypeError, ParamValidationError, ProjectNotFoundError, QueryError,
  RateLimitError, RegionProbeError, RegionProbeNetworkError,
  ReplayNotFoundError, ResponseValidationError, ServerError,
  SessionReplayAccessError, SessionReplayError, SignedURLExpiredError,
  UnsupportedReplayFormatError, WorkspaceScopeError
- **TypedDicts (5)** — all ported (compile-time interfaces, tsc-only lock by design):
  FlowEdge, FlowStepNode, FunnelStepData, QueryMeta, RetentionCohortData
- **functions (5)** — ALL deferred with owner:
  default_label_fn [→ B5], login_unified [→ B7], selector_label_fn [→ B5],
  url_normalizer [→ B5], validate_bookmark [→ B2]
- **Annotated union (1)** — ported: Account
- **union alias (1)** — ported: PropertySpec
- **int const (1)** — ported: BUSINESS_CONTEXT_MAX_CHARS
- **class (1)** — deferred: Workspace [→ B6]
- **namespace modules (3)** — deferred: accounts [→ B7], session [→ B7], targets [→ B7]

## A2 Translated-test assertion fidelity

Sampled three suites across three packets, name-by-name and assertion-by-assertion:

- **`SegmentationResult`** (`packages/core/test/types/results/types.test.ts` vs
  `tests/unit/test_types.py::TestSegmentationResult`): all 5 tests present under
  the Python names; every assertion carried over (`rowColumns()` for
  `df.columns`, `toHaveLength(4)` for `len(df) == 4`, empty-series case, JSON
  serializability). `test_df_cached` is honestly adapted to a determinism check
  and labeled as such (identity caching is a pandas artifact; design C6 says "no
  caching needed").
- **`UserQueryResult`** (`user-query-result.test.ts` vs
  `tests/test_types_user_query_result.py`, 80 Python tests): 72 ported under
  Python names; the 9 not ported are exactly the 7 `test_cannot_set_*`
  frozen-dataclass tests (runtime freezing excluded by R4.6/R4.7 [ST] — no
  `Object.freeze`) and 2 `_df_cache`-population tests (pandas artifact), all
  **documented in the file header with design citations**. Spot-checked the
  hard assertions: the column reorder (`distinct_id` first, `last_seen` second,
  remainder alphabetical) and the sorted-properties assertion are transcribed
  exactly (`cols.slice(2)` vs `cols[2:]`); pandas-NaN semantics honestly mapped
  to absent row keys per C6.
- **Errors** (`packages/core/test/errors.test.ts`, 55 tests, +
  `conformance-runner/test/error-codes-registry.test.ts`, 8 tests, vs
  `tests/unit/test_exceptions*.py`): all Python behaviors present — `toDict()`
  exact key set, absent-vs-null detail keys (R4.11), form-URL prefill both
  branches, catch-all `instanceof` chains, `cause` threading, `ValidationError`
  conditional `suggestion`/`fix` emission, replay-subclass defaults, and
  `name === constructor.name` for every class. Dropped-only: Python dual-
  inheritance tests (`catchable_as_value_error` etc.) — explicitly excluded by
  design C3 ("no JS analog and none is needed"); `__all__`-membership tests —
  superseded by the C8(c) registry-equality test.
- Repo-wide: **zero** `it.skip` / `describe.skip` / `.todo` / commented-out
  assertions in `packages/core/test` and `conformance-runner/test`.
- R10.7 bug-compat spot-check: the saved-flows `"NaN"`-string shape is
  replicated (not fixed) in `live-query.ts` (~1690) with the probe rationale.

## A3 `@internal` discipline vs published `.d.ts`

The repo emits no declarations by default (`noEmit`, private packages). Audit
probe: `tsc -p packages/core --emitDeclarationOnly --declaration --stripInternal`
into a temp dir — **compiles clean (exit 0)**. In the stripped output:

- `Filter`'s 8 `_`-prefixed fields: **absent from the class declaration**
  (present only in the `FilterFields` constructor-bag interface — see nit).
- All `fromDict` statics on result classes: **stripped** (only doc-comment
  mentions remain).
- `sanitizeRawCohort`: **stripped**, and not exported from the package barrel
  (module-level export reaches the conformance binding only — per C1).
- `result-base.ts` helpers: d.ts is literally `export {}` — fully internal.
- `_df_cache`-family class slots (replays, live-query, query-engine,
  schema-graph): **stripped from class declarations**.
- Test plumbing re-exported for locks (`LITERAL_ALIAS_VALUES`, `ENUM_TABLES`,
  `LiteralAliasCoverageProof`): tagged `@internal`, **stripped**.
- `types/vector-codecs.ts`: not re-exported from the package barrel at all.

*Nit A3-n1 (informational)*: the `*Fields`/`*Init` constructor-bag interfaces
retain their `_`-spelled optional members (e.g. `ReplaySummaryFields._df_cache?`)
in the stripped d.ts. Unavoidable: the public constructors accept those bags and
the wire spelling is contractual (R7.6); the design's `@internal` field rule is
about the class surface, which is clean. No action required.

## A4 R3.9/R4.10/R4.11 spot-check — 10 random models

Sample (seeded `random.Random(21008).sample(sorted(models), 10)`):
`CreateCustomPropertyParams`, `CreateRcaDashboardParams`, `BulkUpdateAnomalyParams`,
`BlueprintCard`, `ProjectWebhook`, `UpdateCohortParams`, `BookmarkMetadata`,
`OAuthTokenAccount`, `UpdateDropFilterParams`, `UpdateTagParams`.

For each, the Python `model_fields` dump (annotation, required, default, alias
triple, `model_config.extra`) was diffed against the TS source:

- **Optionality spelling (R3.9)**: every `T | None = None` init-bag field is
  `readonly f?: T | null | undefined` — verified in `CreateCustomPropertyParamsInit`
  (all 9 optional fields) and `OAuthTokenAccount` (`default_project`/`token`/
  `token_env`). No bare `?: T` shortcuts found in the sample.
- **Field order + alias parity**: `fieldSpecs` arrays mirror Python
  `model_fields` order; camelCase `AliasChoices`/`to_camel` sets ported
  explicitly per field (`resourceType`, `displayFormula`, …;
  `BlueprintCard.card_type` ↔ alias/wire `type`) — no generic camelizer (R3.4).
- **Extra policies**: `allow` (`BlueprintCard`, `ProjectWebhook`,
  `BookmarkMetadata`), `forbid` (`OAuthTokenAccount`, via `forbidExtraKeys`),
  Pydantic-default `ignore` (the 6 params models) — all match.
- **R4.10/R4.11**: `OAuthTokenAccount`'s exactly-one-of validator uses Python's
  `is not None` semantics on both sides (absent and explicit `null` both count
  as unset) and the parse result uses the per-branch object-literal idiom
  (`...(token !== undefined ? { token } : {})`) so absent stays absent and
  explicit `null` is preserved. Enum-valued `ProjectWebhook.auth_type` checks
  the Python value set (`oneOf(["basic"])` = `WebhookAuthType` values).

10/10 conform.

## A5 Golden-table completeness

**(i) Result classes (C8b table honesty, verified independently):** I scanned all
corpus JSONL for wire vectors whose `expect.result` is a Python *dataclass walk*
(distinguishable from raw response bodies by the recorder's declared-field
emission, e.g. `_df_cache: null`). Result: exactly 9 apis carry walk-shaped
`expect.result` (`workspace.{funnel,retention,frequency,activity_feed,
segmentation_numeric,segmentation_sum,segmentation_average,query_saved_report,
query_saved_flows}`) — **all 9 are rows of the hand-maintained table** in
`conformance-runner/test/result-goldens.test.ts`, plus the table's 10th row
`api_client.export_profiles_page` (`ProfilePageResult`, walk without a
`_df_cache` marker). The apparent gaps I chased down (`api_client.segmentation`,
`api_client.event_counts`, `api_client.property_counts`,
`api_client.list_bookmarks`) all carry **raw response bodies**, not dataclass
walks (`{"data": {...}, "legend_size": ...}` — Python's `api_client` tier returns
raw dicts); locking those is the documented C8 deferral "result parsing from raw
API response bodies → Phase 3 B5/B6". Result classes without walk vectors are
locked by translated `.df`→`toRows` suites + empty-case goldens (C8b note) and,
for the replay family, by their live `types.*` vectors. The table also carries
per-row honesty tests (vectors-exist assertion) and the three anti-vacuity
probes (unknown-key mutation, `instanceof`, `Object.keys(toJSON())` equality).
**Complete.**

**(ii) Entity models:** `conformance/contract/model-coverage.json`
(`generated_from f6383aa`) holds **exactly the 125 exported Pydantic model names**
(set-equal with the live `__all__` partition — zero missing, zero extra).
Status split: 56 `corpus_tag` + 38 `entity_golden` + 31 `authored_fixture`;
**zero deferral rows, zero unresolved**. Sampled verification: all 31
`authored_fixture` models appear by name in
`packages/core/test/types/entities/authored-fixtures.test.ts`; 5 randomly
sampled `entity_golden` models' vector ids (18 ids) all exist in the corpus
snapshot. The entity-golden suite (`conformance-runner/test/entity-goldens.test.ts`)
is artifact-driven from this file. **Complete.**

## A6 Guard-order parity — 5 multi-guard constructors

Sampled `ReplaySummary` (RS1–RS4), `FrequencyFilter` (FF1–FF5), `Metric`
(EV1/EV2 → V13 → V26 → MT2), `UserAction` (UA1/UA2), `FunnelStep` (EV1/EV2).
Beyond reading the transcribed guard blocks (source order, one comment per code
— all match), parity was verified **behaviorally**: 12 multi-invalid probe
inputs were constructed on both sides (Python via the live package; TS via an
esbuild-bundled throwaway probe against `packages/core/src`, no repo files
touched). All 12 `{class, code}` pairs identical, including the
first-failing-guard-wins cases (`RS1`→`RS2`→`RS3` peeling, `FF1`→`FF2`→`FF3`
peeling, `UA1` before `UA2`, blank-beats-control-char `EV1` vs `EV2`).
**12/12 match.**

## A7 `TODO(port)` triage

Repo-wide grep (`packages`, `conformance-runner`, `differential`, `scripts`):
16 source/test hits + 2 `dist/` bundle copies of one of them. Every one is
triaged with a named owner:

| Site | Owner |
|---|---|
| `flow-query-result.test.ts`, `flow-tree-node.test.ts`, `schema-graph.test.ts`, `replays.test.ts` (4 hits), `replays.ts`, `query-engine.ts` (2), `discovery.ts` — networkx/anytree/rrweb-analyzer graph surfaces | Phase-3 **B5** |
| `bookmarks/enums.ts` — module-private `_MAX_FUNNEL_STEPS`/`_MAX_HOLDING_CONSTANT` ints | Phase-3 **B2/B3** (explicit Risk #8 citation in the comment) |
| `auth/token.ts` — `expires_at` ISO rendering (`+00:00`/µs vs `Z`/ms), nothing locks it in Phase 2 | Phase-3 **B8** oauth_flow wire vectors (+2 dist-bundle copies) |
| `filter.ts:809` / `filter.test.ts:537` — references to the `inCohort` inline-definition stub | **CLOSED** by P2-9 (historical mention only; the branch now calls `sanitizeRawCohort(toDict())` and is vector/differential-locked) |

No untriaged or owner-less markers. **PASS.**

## A8 Conformance counts vs the P2-8 checkpoint

Live re-run (`npm run conformance`):
`{total: 3179, passed: 461, failed: 0, skipped_unported: 2718, failures: []}`
@ corpus `8ae76314a0a6` — **byte-identical to the `report` block of
`context/phase2/p2-8-conformance-report.json`**. Breakdown independently
re-derived with id filters: `compat.` 34/34 PASS, `wirestub` 8/8 PASS (= the
42-vector D13 gate), leaving 419 `types.*` PASS — matching the checkpoint's
`pass_breakdown` (419 + 34 + 8) and its `expected_minimum_pass` floor
(≥395 types.* + 42 gate). **PASS.**

## A9 Common done-criteria re-execution

- `npm run check` (typecheck --workspaces / eslint / prettier-check / vitest /
  browser smoke): **exit 0** — 62 test files, **1880 passed, 2718 skipped
  (UNPORTED sweep placeholders), 0 failed**. This includes every applicable C8
  lock: codec sweep (C8a, no allowlist), result + entity goldens (C8b),
  registry-equality + guard replay + error shapes (C8c), bookmark-enum and
  literal-alias locks (C8d), `batch-status` verdict tests, raw-payload audit.
- `tsc --strict` clean per package (via the workspace typecheck) plus the
  declaration-emit probe in A3.
- 42 pre-existing gate PASSes re-verified individually (A8).
- Python side: this audit adds documentation only (`context/phase2/audit/`);
  no `src/`, `tests/`, or `conformance/` code was touched, and the working tree
  carries no other changes. The support branch's own gates were last exercised
  by P2-9 (`just check` recorded green in commit `2d80135`); nothing in this
  packet invalidates them.

## Nits (informational, no action required this phase)

1. **A3-n1**: `*Fields`/`*Init` bag interfaces keep `_`-spelled optional members
   in stripped d.ts output (constructor-signature necessity; class surfaces are
   clean).
2. **A1-n1**: runtime-kind classifiers must special-case `Account` (Annotated
   unions are callable); recorded so future coverage tooling doesn't misbin it.
