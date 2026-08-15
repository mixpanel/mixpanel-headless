# Phase-2 Design — Contract Layer (types, errors, auth model, vector locking)

**Status**: COMPLETE — executable spec for the Phase-2 contract-layer build
**Date**: 2026-08-15
**Source of record**: Python repo branch `ts-port/phase1-addendum`; TS repo `mixpanel-headless-ts` branch `main`.
**Binding inputs**: typescript-port-plan.md §4.1/§4.2/§6-Phase-2/App-B, rulebook §3/§4/§5/§7 + R10.9/R10.10/R10.13, phase1-design.md + escalation-resolutions.md (E4), coding-pass-design.md, api-map.

## Ground-truth inventory (measured on `ts-port/phase1-addendum`, 2026-08-15)

All counts below were measured live; where they contradict the plan/api-map, see the
Discrepancy Log.

- `mixpanel_headless.__all__` = **284 entries / 274 DISTINCT names** (api-map says
  281; the +3 are the addendum exceptions
  `ParamValidationError`/`ParamTypeError`/`ResponseValidationError`). Ten Literal-alias
  names appear TWICE in `__all__` (`MathType`, `PerUserAggregation`, `FunnelMathType`,
  `RetentionAlignment`, `RetentionMode`, `RetentionMathType`, `CustomPropertyType`,
  `FilterOperator`, `FilterPropertyType`, `FilterDateUnit`) — a recorded Python-side
  latent nit (Discrepancy Log #9); do NOT fix mid-phase; all name-keyed artifacts and
  coverage maps key on the 274 distinct names.
  Runtime-kind partition over distinct names: **37 `Literal` aliases · 8 `Enum`
  classes (7 str, 1 int: `AlertFrequencyPreset`) · 59 dataclasses · 125 Pydantic
  models · 28 exception classes · 5 TypedDicts · 5 functions (`login_unified`,
  `validate_bookmark`, `default_label_fn`, `selector_label_fn`, `url_normalizer`) ·
  1 union alias (`PropertySpec`) · 1 int const (`BUSINESS_CONTEXT_MAX_CHARS`) ·
  `Workspace` · 3 namespace modules (`accounts`, `session`, `targets` — Phase 3) ·
  `Account` (Annotated union)** = 274.
- `exceptions.py`: 28 exception classes + `ValidationError` (a dataclass, NOT an
  exception) + `CODED_GUARD_REGISTRY` (**120 codes**, frozenset) + `CODED_GUARD_TWIN_CODES`
  (9 pre-existing twin codes). Base carries `.code`/`.message`/`.details`/`to_dict()`.
- `types.py` = 13,938 LOC: 24 result dataclasses implement `.df` (all follow the
  rows-list pattern, below); every result/param class has `to_dict()` where serialized.
- Corpus snapshot in the TS repo (`conformance-runner/corpus/`, manifest
  `source_commit d5627564`): manifest `total` = **3,007 extracted** vectors; 3,322 JSONL
  lines on disk incl. authored (compat/wirestub/parse). **395 vectors have
  `call.api` = `types.*`** (all `builder`-kind: constructors, factory methods,
  `CohortDefinition.to_dict`, `_sanitize_raw_cohort`) — these are Phase-2 replayable
  without any client. Distinct `$type` tag universe in the corpus: **85 tags** —
  **5 built-ins with corpus occurrences** (`datetime` 68, `SecretStr` 20, `bytes` 18,
  `callback` 17, `float` 2; the sixth codec-table built-in **`date` has ZERO corpus
  occurrences** — it stays registered but unexercised) **+ 80 rich
  dataclass/Pydantic-model tags**, **every one of which is a Phase-2 type** (incl.
  `OAuthTokens`). Tag counting MUST be JSON-aware (recursive `$type`-key walk), not
  grep-based: a naive grep sees an 86th pseudo-tag from an escaped `\"$type\"`
  inside a string payload.
- Pydantic-model tag coverage: only **56 of the 125** exported Pydantic models occur
  as `$type` tags anywhere in the corpus; the other **69** (incl. `Dashboard`,
  `Cohort`, `Bookmark`, `CustomAlert`, `Annotation`, `FeatureFlag`, `Experiment`,
  `ProjectWebhook`, `EventDefinition`, `PaginatedResponse`, the auth/session
  models) get their runtime lock from the C8(b) entity-golden mechanism (entity
  wire vectors carry plain `expect.result` payloads — measured: 535 of 608 vectors
  in `corpus/entities/` alone) plus the P2-1 per-model coverage artifact.
- `conformance/vectors/api-index.json`: 396 entry points — 60 `builder` + 10
  `validator` + 323 `wire_api` + 3 `wire_state`. **39** of the builder entries are
  `types.*` names; the Python D4 recorder registry carries **40** `types.*` names
  (`types.CohortCriteria.did_not_do_event` is registered but has zero recorded
  vectors, hence absent from the api-index). **`types.FunnelStep` and
  `types.RetentionEvent` appear in NEITHER** the api-index nor the recorder
  registry despite carrying real `__post_init__` guards
  (`_validate_event_name` → FS-family codes; `types.py` ~9992 / ~10324), and the
  public factories `CohortCriteria.property_is_set` / `property_is_not_set` are
  likewise unregistered — P2-1 closes these five coverage holes (see C10).
- TS repo: `packages/core/src/{types,auth}/index.ts` and `errors.ts` are empty
  placeholders; `conformance-runner/src/codecs.ts` already ships a `CodecRegistry`
  with `register(tag, decoder)` (built-ins locked, duplicate registration throws) and
  `bindings.ts` is the single wiring point (currently `compat.*` + `wirestub.*` = the
  42 PASS vectors).

## C1 Package layout (`packages/core`)

Per plan §4.1 / D11, all Phase-2 code lands in `@mixpanel-headless/core`. Kebab-case
files (R7.1), ESM, `tsc --strict` + `exactOptionalPropertyTypes` + `noUncheckedIndexedAccess`.
No `node:*` imports anywhere in core (R9.1).

```
packages/core/src/
├── errors.ts                    # all 28 exception classes (C3)
├── errors-codes.gen.ts          # generated mirror of the Python code registry (C3) — read-only
├── coerce.ts                    # R4.12 Pydantic-lax coercion module (coerceInt/coerceStr/coerceBool/…)
├── secret.ts                    # Secret wrapper (R4.6, C4)
├── invariant.ts                 # R6.8 invariant() helper (throws MixpanelError)
├── auth/
│   ├── account.ts               # ServiceAccount/OAuthBrowserAccount/OAuthTokenAccount union, Region,
│   │                            #   AccountType, TokenResolver interface, id aliases (C4)
│   ├── session.ts               # Session, Project, WorkspaceRef, ActiveSession (C4)
│   ├── token.ts                 # OAuthTokens, OAuthClientInfo (needed: `$type: OAuthTokens` is in corpus)
│   └── index.ts                 # barrel
├── bookmarks/
│   └── enums.ts                 # port of _internal/bookmark_enums.py constant tables (C2)
├── types/
│   ├── literals.ts              # the 37 distinct Literal aliases as literal unions + runtime member arrays (C2)
│   ├── enums.ts                 # the 8 Python Enum classes (C2)
│   ├── query-params/            # the $type dataclass families (C7)
│   │   ├── filter.ts            # Filter, ListItemGroupMode, PropertyInput,
│   │   │                        #   CustomPropertyRef, InlineCustomProperty
│   │   ├── group-by.ts          # GroupBy
│   │   ├── metric.ts            # Metric, CohortMetric, Formula, TimeComparison
│   │   ├── cohort.ts            # CohortCriteria, CohortDefinition, CohortBreakdown,
│   │   │                        #   sanitizeRawCohort (@internal)
│   │   ├── funnel.ts            # FunnelStep, Exclusion, HoldingConstant
│   │   ├── retention.ts         # RetentionEvent
│   │   ├── flow.ts              # FlowStep
│   │   └── frequency.ts         # FrequencyBreakdown, FrequencyFilter
│   ├── results/                 # result dataclasses (C6)
│   │   ├── result-base.ts       # toRows()/toJSON() conventions, Row type (@internal helpers)
│   │   ├── live-query.ts        # SegmentationResult, FunnelResult(+Step), RetentionResult(+CohortInfo),
│   │   │                        #   EventCountsResult, PropertyCountsResult, ActivityFeedResult(+UserEvent),
│   │   │                        #   FrequencyResult, Numeric{Bucket,Sum,Average}Result, SavedReportResult
│   │   ├── query-engine.ts      # QueryResult, FunnelQueryResult, RetentionQueryResult,
│   │   │                        #   FlowQueryResult(+FlowTreeNode), UserQueryResult, FlowsResult
│   │   ├── discovery.ts         # FunnelInfo, SavedCohort, BookmarkInfo, SubPropertyInfo, TopEvent,
│   │   │                        #   Lexicon{Metadata,Property,Definition,Schema}, SchemaGraphResult,
│   │   │                        #   ProfilePageResult
│   │   ├── replays.ts           # ReplaySummary, SignedReplay, UserAction, ReplayEvent, Replay, ReplayBundle
│   │   └── typed-dicts.ts       # QueryMeta, FunnelStepData, RetentionCohortData, FlowStepNode, FlowEdge
│   ├── entities/                # the 125 Pydantic entity/param models (C5)
│   │   ├── common.ts            # PublicWorkspace, CursorPagination, PaginatedResponse<T>
│   │   ├── dashboards.ts        # Dashboard family + Blueprint* + Rca* + UpdateReportLink/TextCard
│   │   ├── bookmarks.ts         # Bookmark family + history
│   │   ├── cohorts.ts           # Cohort, Create/Update/BulkUpdate cohort params
│   │   ├── feature-flags.ts     # FeatureFlag family
│   │   ├── experiments.ts       # Experiment family
│   │   ├── annotations.ts       # Annotation family
│   │   ├── webhooks.ts          # ProjectWebhook family
│   │   ├── alerts.ts            # CustomAlert family (E4: derived from Python + wire vectors)
│   │   ├── lexicon.ts           # EventDefinition/PropertyDefinition/tags/bulk params
│   │   ├── data-governance.ts   # DropFilter, CustomProperty, LookupTable, CustomEvent families
│   │   ├── schemas.ts           # SchemaEntry + enforcement + audit + anomalies + deletion requests
│   │   ├── business-context.ts  # BusinessContext, BusinessContextChain, BUSINESS_CONTEXT_MAX_CHARS
│   │   └── accounts.ts          # AccountSummary, MeUserInfo, AccountTestResult, Target, OAuthLoginResult
│   └── index.ts                 # barrel re-exporting the public surface
└── compat/                      # exists (B0 slice); Phase 2 adds nothing here
```

**Public vs `@internal`** (R2.8, R7.6):

- Public = exactly the 274-distinct-name `__all__` surface that is a *type/error/auth* concern
  (everything except `Workspace`, the 3 namespace modules, `login_unified`,
  `validate_bookmark`, and the 3 replay-label fns — those are Phase-3 B2/B5/B6/B7).
  `packages/core/src/index.ts` re-exports them; JSDoc on every one (R1.3).
- `/** @internal */` (public member, excluded from published `.d.ts`): every
  codec-visible field whose Python name is `_`-prefixed (`Filter._list_item_filters`,
  the `_df_cache` slot, `_sanitize_raw_cohort` → exported from the module for the
  conformance binding but not from the package barrel), `fromDict`/`fromVector`
  constructors used by golden tests, and `result-base.ts` helpers.
- Codec-visible property names keep their **exact Python spelling** — including
  leading underscores and snake_case — because vector `$type` payload keys are the
  cross-language contract (R7.6 wire-spelling exception). Non-serialized locals and
  method names are camelCase as usual.

## C2 Literal aliases + enums

**Where the aliases live (Python, measured):**

| Source module | Count | Examples |
|---|---|---|
| `src/mixpanel_headless/_literal_types.py` | 32 | `TimeUnit`, `MathType`, `FilterOperator`, `FrequencyFilterOperator`, `FlowNodeType`, … |
| `src/mixpanel_headless/types.py` (module level) | 3 public | `BookmarkType`, `SavedReportType`, `EntityType` (`BookmarkTypeLiteral` and `_REPLAY_ACTION_LITERAL` exist in `types.py` but are NOT in `__all__` — not public, no TS export) |
| `src/mixpanel_headless/_internal/auth/account.py` (via `auth_types`) | 2 | `Region`, `AccountType` |
| re-exported through `__init__` | — | total **37 DISTINCT Literal aliases** in `__all__` (`__all__` lists 10 of them twice — see Ground-truth inventory / Discrepancy Log #9; artifacts key on distinct names) |
| `types.py` Enum classes | 8 | `FeatureFlagStatus`, `ServingMethod`, `FlagContractStatus`, `ExperimentStatus`, `WebhookAuthType`, `AlertFrequencyPreset` (IntEnum), `PropertyResourceType`, `CustomPropertyResourceType` |
| `_internal/bookmark_enums.py` | 34 constants | `VALID_CHART_TYPES`, `MAX_CONVERSION_WINDOW` (dict), `MATH_REQUIRING_PROPERTY`, … |

**Enumeration mechanism — generated contract artifact, not hand transcription.**
A Python generator (see C3 for where it lives) introspects `mixpanel_headless.__all__`
+ `mixpanel_headless.auth_types.__all__`, selects every name where
`typing.get_origin(obj) is Literal` or `issubclass(obj, enum.Enum)`, and emits
`conformance/contract/literal-aliases.json`:

```json
{ "generated_from": "<git SHA>",
  "literal_aliases": { "TimeUnit": ["day", "week", "month"], ... 37 entries (distinct names) ... },
  "enums":  { "FeatureFlagStatus": {"kind": "str", "members": {"ACTIVE": "active", ...}},
              "AlertFrequencyPreset": {"kind": "int", "members": {...}} },
  "newtypes": { "AccountName": "str", "ProjectId": "str", "WorkspaceId": "int", "TargetName": "str" } }
```

Member order = Python declaration order (contractual for nothing, but kept stable so
diffs are readable). The TS build ships a **hand-written** `literals.ts`/`enums.ts`
(readable, JSDoc'd) plus a vitest snapshot test that loads the artifact and asserts
set-equality per alias — hand-written source, machine-verified sync. Re-sync = re-run
generator on the Python side, `sync:corpus`, and the test tells you exactly which
alias drifted.

**Representation (R4.3 applied):**

- All 37 distinct Python `Literal` aliases → **string-literal union types**, each with a
  sibling runtime tuple for membership checks:
  `export type TimeUnit = 'day' | 'week' | 'month';`
  `export const TIME_UNIT_VALUES = ['day', 'week', 'month'] as const satisfies readonly TimeUnit[];`
  (The `satisfies` pattern plus an `Exclude<TimeUnit, typeof TIME_UNIT_VALUES[number]> extends never`
  check makes union⇄array drift a compile error.) **This includes `BookmarkType`**:
  R4.3's "string enum for `BookmarkType`" example predates the api-map; the Python
  source defines it as a `Literal` alias and R4.3 simultaneously mandates literal
  unions for "the ~50 Python `Literal` aliases". Ruling here: *the Python source kind
  decides* — `Literal` alias → literal union; `enum.Enum` class → TS enum. Recorded in
  the Discrepancy Log; no escalation (both readings satisfy the wire contract, since
  enum snapshot/serialization compares VALUES, not TS-side representation).
- The 7 Python `str` Enums → **TS string enums** (closed wire domains, referenced by
  member name in Python call sites).
- `AlertFrequencyPreset` (IntEnum) → `const` object + numeric literal union
  (R4.3 IntEnum rule; preserve numeric values).
- The 4 `NewType` identifiers (`AccountName`, `ProjectId`, `WorkspaceId`,
  `TargetName`) → **plain type aliases** (`type ProjectId = string`), NOT branded
  types. Rationale: Python's NewType is erased at runtime and the public facade
  deliberately accepts bare `str`; brands would force casts at every mechanically
  translated call site for zero wire-contract gain. Documented in JSDoc.
- `PropertySpec` union alias → TS union alias; `BUSINESS_CONTEXT_MAX_CHARS` → `const`.
- `bookmarks/enums.ts` ports the 34 `_internal/bookmark_enums.py` constants. Python
  `frozenset`s/lists become `ReadonlyArray` and the dict constants
  (`MAX_CONVERSION_WINDOW`, …) become `ReadonlyMap` per R4.8 (membership tests use
  `.has()`), with a serialization view for the snapshot test.

**How the enum snapshot vectors lock the tables:** `conformance/vectors/enums/bookmark_enums.json`
(already extracted; `source_module: mixpanel_headless._internal.bookmark_enums`, 34
constants) is loaded by a vitest suite that serializes each TS table with the same
normalization the extractor used (lists sorted, dict keys sorted) and canonical-diffs
per constant. The literal-alias artifact test does the same for
`literals.ts`/`enums.ts`. Together these are the C8(d) enum locks. The rrweb numeric
IntEnums are *not* Phase 2 (they live in `_internal/replays/`, batch B5) — deferral
recorded in C8.

## C3 Exceptions + code registry

**Class port (R5.1/R5.2).** All 28 Python exception classes port to `errors.ts` as
`Error` subclasses preserving names, in the same hierarchy:

```
MixpanelHeadlessError extends Error          # base: code, message, details, toDict(), cause
├── ParamValidationError                     # addendum; default code "VALIDATION_ERROR"
├── ParamTypeError                           # addendum; default code "VALIDATION_ERROR"
├── ResponseValidationError                  # addendum; default code "RESPONSE_VALIDATION_ERROR"
├── APIError                                 # + statusCode/responseBody/request context fields
│   ├── AuthenticationError · RateLimitError · QueryError · ServerError
│   └── SessionReplayError
│       ├── SessionReplayAccessError · SignedURLExpiredError
│       ├── ReplayNotFoundError · UnsupportedReplayFormatError
├── ConfigError
│   ├── AccountNotFoundError · ProjectNotFoundError · AccountExistsError
│   ├── InvalidArgumentError · AccountInUseError
├── OAuthError
│   └── RegionProbeError → RegionProbeNetworkError
├── EventNotFoundError · DateRangeTooLargeError · WorkspaceScopeError
└── BusinessContextValidationError · BookmarkValidationError
```

Every class: `this.name = this.constructor.name` in the base constructor; `readonly
code: string`, `readonly details: Readonly<Record<string, unknown>>` (R4.9 — Python
`dict[str, Any]`), standard `cause` via `ErrorOptions`; `toDict(): {code, message,
details}` matching Python's `to_dict()` key set byte-for-byte. Subclass constructor
*signatures* mirror the Python ones (e.g. `APIError` takes the request/response
context options bag; `RateLimitError` keeps its form-URL details construction —
message TEXT is out of contract per R5.4, so the form-URL helper string is copied but
never asserted). Python's dual inheritance (`ParamValidationError(MixpanelHeadlessError,
ValueError)`) has no JS analog and none is needed: the conformance key is class name +
code (R5.2), not builtin-ness. `ValidationError` (the dataclass) ports as a plain
class in `errors.ts` with fields **exactly as Python defines them
(`exceptions.py:1255+`): `path: string`, `message: string`,
`code: string = "VALIDATION_ERROR"`, `severity: 'error' | 'warning' = 'error'`,
`suggestion?: readonly string[] | null` (Python `tuple[str, ...] | None`),
`fix?: Readonly<Record<string, unknown>> | null`** — there is NO `field`
attribute. Its `toDict()` always emits `{path, message, code, severity}` and
conditionally adds `suggestion` (tuple → JSON array) and `fix` ONLY when
non-`None`, byte-matching Python's `to_dict` (it rides inside
`BookmarkValidationError.errors` and `oracle` error payloads). The two rulebook R5.1 client-side classes
(`MixpanelApiError`/`MixpanelHttpError`) are **Phase-3 B4** (they wrap transport
outcomes; nothing in Phase 2 can construct them meaningfully) — noted as deferred.

**Code registry strategy: GENERATE, don't hand-port.** Decision: a Python-side
generator emits `conformance/contract/error-codes.json`; the TS side commits a
mirror `errors-codes.gen.ts` (or loads the JSON directly in tests — see below).

- **Generator**: `conformance/contract/generate_contract.py` (new module; also emits
  the C2 `literal-aliases.json` and the C8 `tag-universe.json`). Pure introspection:
  ```json
  { "generated_from": "<git SHA>",
    "exception_classes": {"MixpanelHeadlessError": null, "APIError": "MixpanelHeadlessError", ...28 entries: name → parent name...},
    "default_codes": {"MixpanelHeadlessError": "UNKNOWN_ERROR", "ParamValidationError": "VALIDATION_ERROR", ...},
    "coded_guard_registry": [...120 codes, sorted...],
    "coded_guard_twin_codes": [...9 codes, sorted...] }
  ```
  Sources: the class objects themselves (MRO walk) and
  `exceptions.CODED_GUARD_REGISTRY` / `CODED_GUARD_TWIN_CODES` — no parsing.
- **Branch discipline**: the generator + artifacts land on a **new Python branch
  `ts-port/phase2-contract-support`, based on `ts-port/phase1-addendum`** (per the
  standing rule: never rewrite the audited addendum history; support tooling gets its
  own branch). It follows repo standards (mypy --strict, docstrings, tests — D17
  scope applies to `conformance/`). `scripts/sync-corpus.sh` (TS repo) is extended to
  also copy `conformance/contract/*.json` into `conformance-runner/corpus/contract/`;
  the corpus `manifest.source_commit` pin is untouched (vectors are unchanged — the
  artifacts carry their own `generated_from` SHA for provenance).
- **Why generate**: 120 + 9 + 28 + defaults ≈ 160 hand-copied strings is exactly the
  transcription-error class the port pipeline exists to eliminate, and the registry
  is *expected to grow* (Phase-3 batches B2/B3 mint nothing new, but any future
  Python coding pass would). One generator, re-run + re-sync, zero drift.
- **Which code families are (and are not) in this artifact — measured against the
  live `CODED_GUARD_REGISTRY`:** the `V*`/`U*`/`UP*` validator-rule codes are
  genuinely ABSENT (they live in `validation.py`/`user_validators.py` logic, Phase 3
  batch B2, locked there by the 680 validation-capability vectors). But
  **`CF1`/`CF2` (Filter.in_cohort family), `CB1`/`CB2` (CohortBreakdown),
  `CA1`/`CA2` (CohortCriteria.did_event), and `UA1`/`UA2` (UserAction) are Phase-2
  constructor-guard codes, and `BB1`–`BB8` are Phase-3 `bookmark_builders` codes —
  all four families ARE in the registry artifact** and MUST appear in the TS mirror
  (the registry-equality gate compares full sets; filtering any of them out fails
  it). Phase 2 locks the full code *universe* via the artifact; Phase 2 code paths
  only *raise* the C7/C6-d guard families + class defaults.

**How vectors lock class-name + code equivalence (C8c):**
1. *Registry equality test* (vitest): parse `corpus/contract/error-codes.json`;
   assert (a) `errors.ts` exports exactly the 28 class names with the same
   parent-edge set (walk `Object.getPrototypeOf` chains), (b) the TS
   `CODED_GUARD_REGISTRY` set (re-exported from `errors-codes.gen.ts`) equals the
   artifact's set, (c) default codes match.
2. *Guard vector replay*: the 395 `types.*` vectors cover the recorded
   guard-failure tests for every C7 family EXCEPT `FunnelStep`/`RetentionEvent`
   and the `did_not_do_event`/`property_is_set`/`property_is_not_set`
   `CohortCriteria` factories, which have zero vectors today — P2-1 adds their
   registry entries + recorded vectors on the support branch so this lock is
   complete before P2-5c/P2-5b consume it; the runner compares
   `expect.error.class` + `expect.error.code` against what the TS constructor threw
   (messages stripped, R5.4). This is the behavioral half — the registry test alone
   can't prove a guard fires with the right code at the right site.
3. *Error-shape unit tests* (translated from `tests/unit/test_exceptions*.py`
   patterns): `toDict()` key set, `name` correctness, `instanceof` chains,
   `cause` threading for `ResponseValidationError`.

## C4 Account/Session model

Ports `_internal/auth/account.py` + `session.py` + `token.py` (public surface =
`auth_types.__all__`). All shapes are **compile-time `readonly` interfaces/classes,
no `Object.freeze`** (R4.6 [ST]).

**Discriminated union (R4.4):**

```ts
export type Region = 'us' | 'eu' | 'in';
export type AccountType = 'service_account' | 'oauth_browser' | 'oauth_token';

export interface ServiceAccount {
  readonly type: 'service_account';
  readonly name: AccountName;            // = string
  readonly region: Region;
  readonly default_project?: ProjectId | null | undefined;  // R3.9 + R4.10, see below
  readonly username: string;
  readonly secret: Secret;               // R4.6 wrapper
}
export interface OAuthBrowserAccount { readonly type: 'oauth_browser'; /* name/region/default_project */ }
export interface OAuthTokenAccount {
  readonly type: 'oauth_token'; /* name/region/default_project */
  readonly token?: Secret | null | undefined;
  readonly token_env?: string | null | undefined;
}
export type Account = ServiceAccount | OAuthBrowserAccount | OAuthTokenAccount;
```

- **Exhaustive narrowing**: every consumer switch ends
  `default: { const _exhaustive: never = account; throw new MixpanelHeadlessError(...) }`.
  A compile-time exhaustiveness test plus a fast-check property (C9) enforce it;
  adding a 4th variant breaks the build.
- **Construction + invariants**: interfaces alone can't carry Pydantic's validators,
  and the corpus decodes `$type`-tagged auth payloads, so each variant gets a factory
  `parseAccount(raw: unknown): Account` (module-level, sync per R3.7) that applies
  the same checks Pydantic enforces: name pattern `^[a-zA-Z0-9_-]+$` (1–64,
  codepoint-counted per R11.6), `default_project` digits-only, `extra='forbid'`
  (unknown keys → error), and the `OAuthTokenAccount` exactly-one-of
  `token`/`token_env` rule. Guard failures throw `ResponseValidationError`
  (config/vector-decode seam) or `ParamValidationError` per the call-path — matching
  Python: Pydantic model construction failures are the generic
  `VALIDATION_ERROR`/`RESPONSE_VALIDATION_ERROR` boundary (R5.5); no new codes are
  minted in TS (the registry is closed for Phase 2).
- `auth_header()` / `is_long_lived()` port as free functions over the union
  (`accountAuthHeader(account, {tokenResolver})`, `isLongLived(account)`) rather than
  methods — interfaces stay data-only and the exhaustive switch lives in one place;
  base64 uses `TextEncoder`-based encoding (no `node:buffer`, R9.1). Async note:
  `TokenResolver` in TS is `getBrowserToken(name, region): Promise<string>` /
  `getStaticToken(account): Promise<string>` (token refresh does I/O — R3.1), so
  `accountAuthHeader` returns `Promise<string>`; R2.5 already relocates refresh to
  per-request `TokenResolver.getToken()` so this changes no observable wire behavior.

**Secret (R4.6).** `secret.ts`:

```ts
export class Secret {
  readonly #value: string;
  constructor(value: string) { this.#value = value; }
  reveal(): string { return this.#value; }
  toString(): string { return '**********'; }
  toJSON(): string { return '**********'; }
  [Symbol.for('nodejs.util.inspect.custom')](): string { return '**********'; }
}
```

- Redaction literal is Pydantic's exact `'**********'` (10 asterisks) so any string
  that *does* leak into a serialized bag diffs identically against Python's.
- ECMAScript `#private` field: invisible to `JSON.stringify`, `Object.keys`, spread,
  and structured logging. The inspect symbol is registered via `Symbol.for` (no
  `node:util` import — R9.1-safe, ignored in browsers). No runtime freeze (R4.6).
- Codec: `$type: "SecretStr"` decodes to `Secret` (superseding the runner's
  placeholder `SecretValue`; see the C7 migration for how the 42 gate PASSes stay
  green).

**Session shapes** (`auth/session.ts`), field names exactly as Python (these cross
into vectors and, in Phase 3, the bridge/config files):

```ts
export interface Project   { readonly id: ProjectId; readonly name?: string | null;
                             readonly organization_id?: number | null; readonly timezone?: string | null; }
export interface WorkspaceRef { readonly id: WorkspaceId; readonly name?: string | null;
                             readonly is_default?: boolean | null; readonly project_id?: ProjectId | null; }
export interface Session   { readonly account: Account; readonly project: Project;
                             readonly workspace?: WorkspaceRef | null;
                             readonly headers: ReadonlyMap<string, string>; }  // R4.8; REQUIRED —
                             // Python: `headers: Mapping[str, str] = Field(default_factory=dict)`
                             // (session.py:145) — never None/undefined; parse fills an empty map.
export interface ActiveSession { readonly account?: AccountName | null;
                             readonly workspace?: WorkspaceId | null; }
                             // NO `project` field: Python's ActiveSession has ONLY
                             // account + workspace with extra='forbid' (session.py:309+);
                             // its docstring explicitly rejects unknown keys INCLUDING
                             // `project` (project lives on Account.default_project —
                             // switching accounts implicitly switches projects).
                             // parseActiveSession MUST reject a `project` key
                             // (extra='forbid' parity); port the docstring rationale.
export interface OAuthTokens { readonly access_token: Secret; /* + refresh_token/expires_at/… per token.py */ }
export interface OAuthClientInfo { /* per token.py */ }
export interface TokenResolver { getBrowserToken(name: string, region: Region): Promise<string>;
                             getStaticToken(account: OAuthTokenAccount): Promise<string>; }  // R6.5
```

(`OAuthTokens` is in Phase-2 scope because `$type: "OAuthTokens"` appears in the
corpus. Exact field lists are read from `_internal/auth/token.py` by the P2-4
implementer; parse factories mirror `parseAccount`. `BridgeFile`/`load_bridge` are
Phase 3 B8 — node-only file I/O.)

**R3.9/R4.10 optionality discipline** (applies to every Phase-2 model, stated once
here): every Python `T | None = None` **data-model field** becomes
`readonly f?: T | null | undefined`. At decode/parse boundaries an absent key stays
absent and an explicit JSON `null` is preserved as `null` (never converted to
`undefined` — the canonicalizer distinguishes them, R4.11). At serialize time
(`toJSON`/`toDict`) the emitter reproduces Python's per-field behavior exactly: if
Python's `to_dict`/serializer emits the key with `None`, TS emits it with `null`; if
Python conditionally omits it, TS uses the per-branch object-literal idiom (R4.11).
The `?` + `| undefined` spelling is mandatory under `exactOptionalPropertyTypes`
(R3.9).

## C5 Generated entity types

**Prime decision: the 125 Pydantic entity/param models are HAND-WRITTEN TS classes
mirroring the Python models field-for-field; the vendored `types.d.ts` files are a
type-level CROSS-CHECK, not the source.** Rationale (this is R4.1 applied through
R10.6 "Python is the arbiter of behavior" and the E4 ruling): the Python models are
what the vectors lock — 700+ `entities`/`data-governance` wire vectors record the
Python field names, alias behavior, and drop-null serialization. The vendored
schema4api surface has holes (cohorts: none; webhooks: iron-only; alerts:
`alerts/custom` only, advisory per E4) and where it exists it describes the server's
view, not `mixpanel_headless`'s (which renames via `AliasChoices`/`to_camel` and
subsets fields). Generating TS from schema4api and then hand-patching every
divergence would invert the authority order E4 just settled.

Mechanics per entity area (`types/entities/*.ts`):

1. **Model port**: one TS class per Pydantic model. Wire-shaped fields keep Python/
   API spelling (R3.6); Pydantic `alias`/`AliasChoices`/`to_camel` configurations are
   ported as explicit `fromDict` (accepts the alias set) / `toDict` (emits the
   serialization alias) logic — never a generic camelizer (R3.4). Lax coercion via
   the shared `coerce.ts` (R4.12); `default_factory` fires only on absent keys.
2. **Vendored cross-check (R4.1/R7.5)**: for each area with a vendored contract, a
   `*.contract.test-d.ts`-style compile-only file asserts assignability between the
   hand-written wire shape and the relevant vendored type (e.g. our
   `AnnotationDict` is assignable to schema4api's annotation response type modulo a
   documented `Omit`/`Pick` list). Vendored files under `vendor/mixpanel-contracts/`
   stay byte-frozen (PROVENANCE.json + `npm run vendor:drift`); nothing imports them
   at runtime — type-level `import type` only, from the check files.
3. **Coverage-hole handling**:
   - *Cohorts*: no schema source exists anywhere → hand-written from Python (already
     the rule), no cross-check file; noted in PROVENANCE `coverage_holes` (already
     recorded).
   - *Webhooks*: cross-check against the vendored iron file
     (`iron/common/types/schema4api/webapp/project_webhooks/types.d.ts`).
   - *Alerts (E4 — MANDATORY verification step, done inside P2-7)*: (i) list the
     endpoint paths Python's alert CRUD actually calls (grep `api_client.py` alert
     methods + the recorded `expect.request.path` values in the alerts wire vectors);
     (ii) diff that surface against the vendored `alerts/custom/types.d.ts`
     assumptions; (iii) TS `CustomAlert`/`CreateAlertParams`/… are derived from the
     Python models + those wire vectors; (iv) every divergence found is appended to
     `vendor/mixpanel-contracts/PROVENANCE.json` under a new
     `verified_divergences.alerts` key (TS repo commit) — the vendored file is never
     edited.
4. **Read-only provenance for OUR generated file**: the only *generated* TS source in
   Phase 2 is `errors-codes.gen.ts` (C3) plus the pre-existing bookmark.json output;
   both carry a `// GENERATED FROM <artifact> @ <sha> — DO NOT EDIT` header and an
   ESLint ignore-free, prettier-formatted body; a unit test regenerates-and-diffs
   (codes) or the referee re-runs `npm run generate` (bookmark) to catch hand edits.

5. **Runtime lock (NOT just compile-time)**: the cross-check files alone are
   insufficient — only 56 of the 125 models occur as corpus `$type` tags, and the
   vendored surface is holed (cohorts: none). Therefore **every entity model gets a
   C8(b)-style golden**: entity/data-governance wire vectors carry plain
   `expect.result` payloads (measured: 535/608 vectors in `corpus/entities/`
   alone), and each model's golden does `fromDict(expect.result)` → `toDict()` →
   canonical-diff, plus the C8(b) anti-vacuity probes. P2-1 emits a per-model
   coverage artifact (`corpus/contract/model-coverage.json`: model → {corpus-tag |
   entity-golden vector ids | authored fixture | deferral row + owner}); a model
   with NONE of the four is a P2-7 failure. This replaces what was previously an
   unnamed deferral.

`bookmark.json`-derived types (`differential/src/generated/reports/bookmark.ts`)
already exist for the referee and are NOT re-homed in Phase 2; the bookmark builder
batch (B3) decides whether builders type against them.

## C6 Result-type shapes

Scope: the **59 exported dataclasses** minus the 21 query-param/filter-family
classes handled in C7 and minus `ValidationError` (a dataclass in `__all__`,
ported in `errors.ts` per C3 — NOT here; the base `ResultWithDataFrame` is not
exported at all and needs no subtraction) → **37 result/info dataclasses** (24 of
which implement `.df`), plus the Pydantic *response* models which follow C5
mechanics. All become plain TS classes with `readonly` fields
(R4.7), **exact Python field names — never camelized** (R3.4), `toJSON()` matching
the Python `to_dict()` dict shape key-for-key, and `toRows()` replacing `.df`.

**The row contract** — NOT uniform; port per-class, `.df` body by `.df` body. The
"one pattern" (build `rows: list[dict[str, Any]]` with hand-named lowercase keys →
`pd.DataFrame(rows)`, empty input → empty frame with a fixed column list, cached in
`_df_cache`) holds for the MAJORITY of the 24 `.df` classes (e.g.
`SegmentationResult` rows `{date, segment, count}`, `FunnelResult` rows `{step,
event, count, conversion_rate}` with `step` starting at 1, `RetentionResult` rows
`{cohort_date, cohort_size, period_0..period_N}` with **ragged keys per cohort** —
pandas' NaN-fill is a pandas artifact and explicitly OUT of the TS contract). But
at least four classes DIVERGE and get **per-class row specs transcribed from their
Python `.df` bodies** (the P2-6 implementer reads each `.df` implementation; no
class may be ported from the generic pattern without checking):

- `SavedReportResult.df` (types.py ~1105): insights branch builds rows; the
  non-insights branch returns `pd.DataFrame([{"series": self.series}])` — a
  SINGLE row whose one `series` cell is the nested dict, branch selected by the
  derived report type. `toRows()` mirrors both branches exactly.
- `FlowsResult.df` (~1180): `pd.DataFrame(self.steps)` if steps else
  `pd.DataFrame()` — the empty case has **NO column list** (empty
  `rowColumns()`), and rows are the raw step dicts, not hand-named keys.
- `QueryResult.df` (~9765): picks among FOUR column layouts (timeseries / total /
  segmented timeseries / segmented total) and passes an explicit `columns=cols`
  list per branch — columns are data/mode-dependent.
- `UserQueryResult.df` (~11953): FIVE branches plus a post-frame column reorder
  (`distinct_id` first, `last_seen` second, remaining alphabetical, ~12059) —
  the reorder IS part of the row/column contract.

Mechanism corrections that follow:

- `toRows(): ReadonlyArray<Record<string, unknown>>` returns exactly the rows list
  Python builds before it enters pandas (or the branch-specific equivalent above).
- **`rowColumns` is an instance method, `rowColumns(): readonly string[]` — NOT a
  static** (for `QueryResult`/`UserQueryResult` the column list is data-dependent;
  for the uniform classes it returns the Python empty-frame constant and doubles as
  the CSV-header contract; for `FlowsResult` it returns `[]`).
- **Multi-DataFrame surfaces are IN scope**: `FlowQueryResult` exposes `nodes_df` /
  `edges_df` (+ `trees_df`) and `SchemaGraphResult` exposes `events_df` /
  `properties_df` / `relationships_df` — each auxiliary frame gets its own
  `to*Rows()` method (`toNodesRows()`, `toEdgesRows()`, `toTreesRows()`,
  `toEventsRows()`, `toPropertiesRows()`, `toRelationshipsRows()`) transcribed
  from the corresponding Python property, with translated tests per frame.
- Codec note: the encode walk emits **ALL declared Python fields**, so the full
  private-cache surface is codec-visible and must exist as fields:
  `FlowQueryResult`: `_df_cache`, `_nodes_df_cache`, `_edges_df_cache`,
  `_graph_cache`, `_trees_df_cache`, `_anytree_cache`; `SchemaGraphResult`:
  `_df_cache`, `_events_df_cache`, `_properties_df_cache`,
  `_relationships_df_cache`, `_graph_cache` (all `@internal`, encoded as `null`
  when unset, exactly as vectors record them).
- No caching needed (row building is cheap and pure); if an implementer adds
  memoization it must be invisible (`#rows` private) and separate from the
  codec-visible `_*_cache` fields above.
- Row values keep Python's types: counts `number`, rates `number`, dates `string`
  (watchlist #5).

**toJSON()**: byte-shape equal to Python `to_dict()` (same keys, same order of
insertion as Python's dict literal — canonicalizer sorts anyway, but emission order
defaults to Python's per §8-10). Nested dataclasses serialize via their own
`toJSON()` exactly as Python calls `step.to_dict()`. `null`-vs-absent per C4's
discipline. Classes without a Python `to_dict` (pure info holders like `TopEvent`)
get `toJSON` only if Python has one — **do not invent serializers**; the P2-6
implementer greps `def to_dict` per class (39 exist in `types.py`) and mirrors
presence/absence.

**`fromDict` (@internal)**: every result class gets a `fromDict(raw)` inverse used
by the C8(b) golden tests and later by Phase-3 parse layers where Python constructs
the dataclass from parsed fields. It applies `coerce.ts` with Pydantic-lax semantics
only where the Python path validates (dataclasses don't coerce — so `fromDict` for
dataclass results is strict: wrong JSON type → `ResponseValidationError`).

**Build batches by capability (Python source order, sizes = class count / approx
Python LOC incl. docstrings):**

| Sub-batch | Classes | Size |
|---|---|---|
| C6-a live-query results | SegmentationResult, FunnelResultStep, FunnelResult, CohortInfo, RetentionResult, EventCountsResult, PropertyCountsResult, UserEvent, ActivityFeedResult, SavedReportResult, FlowsResult, FrequencyResult, NumericBucketResult, NumericSumResult, NumericAverageResult | 15 / ~1,400 |
| C6-b discovery + lexicon | FunnelInfo, SavedCohort, BookmarkInfo, SubPropertyInfo, TopEvent, LexiconMetadata, LexiconProperty, LexiconDefinition, LexiconSchema, ProfilePageResult, SchemaGraphResult | 11 / ~900 |
| C6-c query-engine results | QueryResult, FunnelQueryResult, RetentionQueryResult, FlowTreeNode, FlowQueryResult, UserQueryResult (+ TypedDicts QueryMeta, FunnelStepData, RetentionCohortData, FlowStepNode, FlowEdge as pure interfaces) | 6+5 / ~1,600 |
| C6-d replays | ReplaySummary, SignedReplay, ReplayEvent, Replay, ReplayBundle, UserAction (UserAction is also a D4.4 `$type` family member with UA1/UA2 guard codes — it is BUILT here with the replay models and codec-registered exactly like the C7 classes) | 6 / ~1,200 |

Replay-model constructor guards (RS*/SR*/RE*/RP*/RB* codes in the registry) fire in
the constructors exactly as Python's `__post_init__` does, in the same check order —
their vectors (`types.ReplaySummary` 19, `types.SignedReplay` 15, `types.Replay` 10,
`types.ReplayEvent` 10, `types.ReplayBundle` 2) replay in Phase 2.

## C7 Filter/param types + codec binding

**The family** (the D4.4 `$type` table + nested types, all frozen dataclasses in
`types.py`): `Filter`, `FunnelStep`, `RetentionEvent`, `FlowStep`, `Metric`,
`CohortMetric`, `Formula`, `GroupBy`, `CohortBreakdown`, `FrequencyBreakdown`,
`FrequencyFilter`, `TimeComparison`, `CohortDefinition`, `UserAction`, plus nested
`CohortCriteria`, `CustomPropertyRef`, `InlineCustomProperty`, `PropertyInput`, and
the additional dataclass tags observed in the corpus: `Exclusion`,
`HoldingConstant`, `ListItemGroupMode`. (21 classes; also module-private
`_sanitize_raw_cohort` → `sanitizeRawCohort`, exported `@internal` for its 6
vectors.)

**TS shape: classes, not interfaces.** These carry factory classmethods
(`Filter.on(...)`, `CohortCriteria.did_event(...)`, `CohortDefinition.all_of(...)`),
registry-coded constructor guards (the CF/CB/**CA**/CM/CD/TC/MT/FM/LC/FD/LG/GB/EV/
FB/FF/EX/HC/FS/UA codes — CA1/CA2 fire inside `CohortCriteria.did_event`,
types.py ~8717; the C9 error-branch set is derived from raise-site introspection /
the generator artifact, NOT from this prose list), and serialization methods
(`CohortDefinition.to_dict`). Rules:

- Fields `readonly`, exact Python names — for `Filter` that means **ALL 8 declared
  fields are `_`-prefixed** (`_property`, `_operator`, `_value`, `_property_type`,
  `_resource_type`, `_date_unit`, `_list_item_filters`, `_list_item_quantifier`)
  and every one is codec-visible under its underscore spelling (`@internal` JSDoc
  on all of them); `CohortCriteria`/`CohortDefinition` privates likewise. Python tuples → `ReadonlyArray` (the codec re-encodes arrays;
  tuple-ness is a Python-side reconstruction detail).
- Static factories keep Python's *method* names camelized ONLY where they are not
  wire/vector-visible. They ARE vector-visible: `call.api` is e.g.
  `types.Filter.in_the_last`, and the runner maps snake→camel mechanically on the
  method segment (D12), so the TS methods are `Filter.inTheLast(...)`,
  `CohortCriteria.didEvent(...)`, etc. — the naming map handles the mapping; no
  entries in `naming-exceptions.json` are expected (mechanical rule suffices; verify
  during P2-5 and add exceptions only if the generator flags a collision).
- Guard parity: each guard throws `ParamValidationError`/`ParamTypeError` with the
  registry code, **in Python's check order** (first failing guard wins — vectors
  record one error per input). Empty-collection guards use length checks (watchlist
  #6); string truncation/length checks are codepoint-based (R11.6).
- `CohortDefinition` mirrors Python's `init=False` design: private constructor +
  `allOf(...)`/`anyOf(...)` statics; its codec decoder reconstructs via the statics
  exactly as `conformance/record/codecs.py::_decode_cohort_definition` (lines
  477–508) does: **`_operator === 'or'` → `anyOf(...)`, `_operator === 'and'` →
  `allOf(...)`, ANY other operator → `UndecodableValueError`** (and a static-throw
  during reconstruction wraps into `UndecodableValueError` too). Note the payload
  operators are the stored `'or'`/`'and'` literals (`any_of(...)._operator == 'or'`,
  `all_of(...)._operator == 'and'`) — there is no `'any'` literal and no else-fallback.

**Codec binding (the real migration).** Today `conformance-runner/src/codecs.ts`
decodes only built-ins; dataclass/model tags are unknown (fine for the 42
compat/wirestub PASSes — those vectors carry no rich tags). Phase 2:

1. `packages/core/src/types/vector-codecs.ts` (`@internal`): for every Phase-2 type,
   a `TagCodec` entry `{decode(payload, decodeChild), encode(instance,
   encodeChild)}`. Decode = `fromDict`-style construction through the real
   constructor/factory (guards FIRE on decode — a vector carrying an invalid payload
   is a vector bug and must fail loudly, mirroring Python's `_decode_dataclass`).
   Encode = field-level walk (mirror of Python `_encode_common` `tagged_models=True`:
   ALL declared fields, including `_`-prefixed ones and `null`-valued `_df_cache`
   slots, `$type` first).
2. `bindings.ts` gains one call per Phase-2 packet:
   `registerContractCodecs(codecs)` — uses the existing `CodecRegistry.register`
   (duplicate registration already throws, so double-wiring is caught). Most
   built-in tags are untouched; `SecretStr` is the one built-in whose *product*
   changes (runner `SecretValue` → core `Secret`) — and because `SecretStr` is a
   BUILT-IN, an alias-only migration is impossible: `CodecRegistry.register`
   throws on built-in shadowing (codecs.ts:239), the built-in decode arm
   constructs `SecretValue` in place (codecs.ts:342), and the encoder reads the
   public `.value` field (codecs.ts:425) that core `Secret` hides behind
   `reveal()`/`#value`. **The migration is therefore explicit edits to
   `conformance-runner/src/codecs.ts`**: (i) the built-in `SecretStr` decode arm
   constructs `new Secret(...)` from core; (ii) the encode branch switches to
   `value instanceof Secret` and calls `value.reveal()` (NEVER `toJSON()` — its
   `'**********'` mask in an encoded vector would make mask-vs-mask comparisons
   vacuously equal and is a FAIL); (iii) `SecretValue` survives only as a
   deprecated `type SecretValue = Secret` alias. Gate honesty: the 42
   compat/wirestub PASS vectors carry NO `SecretStr` tags (authored tags there:
   datetime/bytes/float/Filter/CustomPropertyRef/Formula) — the real regression
   surface is the **20 `SecretStr` occurrences in extracted vectors**, locked by
   the C8(a) sweep, which additionally asserts round-tripped `SecretStr` payloads
   preserve the REVEALED value. The 42 must still be green in the same commit
   (compile-level safety), but they are not the SecretStr behavioral gate.
3. The same registration flips the **395 `types.*` vectors** (plus the P2-1
   additions) from `UNPORTED` to live replay: `bindings.ts` registers an
   implementation per `types.*` api-index entry (**39 entries today — constructor
   calls, factory methods, `to_dict`, `sanitizeRawCohort` — rising to 44 after
   P2-1 adds `types.FunnelStep`, `types.RetentionEvent`,
   `types.CohortCriteria.did_not_do_event`, `types.CohortCriteria.property_is_set`,
   `types.CohortCriteria.property_is_not_set`**), each a thin adapter: decode
   kwargs → invoke the real class/static → encode the result (or catch and encode
   `{class, code}` for expect.error vectors).
4. **Batch-done flip (R10.5/D12)**: NOTE — the runner has NO batch table today
   ("declared done" exists only in comments: runner.ts:21, verdicts.ts:16;
   `UNPORTED` is purely implementation-absence, runner.ts:340-359). P2-8 builds
   the module: `conformance-runner/src/batch-status.ts` exporting a declarative
   `Map<apiPrefix, 'pending' | 'done'>`, consumed by the verdict path so that a
   vector whose api matches a `'done'` prefix but lacks a bound implementation
   returns FAIL instead of `UNPORTED`, with a unit test covering both semantics.
   When P2-5/P2-6 packets are declared done, `types.*` flips to `'done'` — no
   silent skips.

`call.input` decoding for *later* phases (wire vectors passing `CreateBookmarkParams`
etc.) uses the same registry — Phase 2 registers ALL 80 rich tags (params models
included, via their C5 classes; `date` stays registered-but-unexercised per C8(a)),
so Phase-3 batches inherit a complete decode table and never hand-roll plain-object
access again.

## C8 Vector-locking mechanism (Phase 2)

Phase 2 has no HTTP client, so "every type locked before anything consumes it" is
implemented as four offline checks over the committed corpus snapshot plus the live
replay of the `types.*` vectors. All four run inside `npm run test` (vitest) and are
part of every packet's done-criteria from the moment their inputs exist.

**(a) Corpus-wide codec round-trip sweep** — `conformance-runner/test/codec-sweep.test.ts`:

- Walk every vector in the snapshot (all 3,322 lines, lossless-JSON parsed). For
  every `$type`-tagged object found anywhere under `call.input` (recursive descent,
  including inside arrays/objects/nested tags): `decode` through the registry into
  the real TS instance, `encode` back, canonical-diff (D6 canonicalizer) against the
  original subtree. Any diff = FAIL with vector id + JSON path.
- **Anti-vacuity (mandatory)**: for every rich tag, the sweep asserts the decoded
  product is `instanceof` the registered core class (a decode-to-plain-object or
  raw-payload-passthrough codec round-trips perfectly and would otherwise pass);
  for `SecretStr`, it additionally asserts the round-trip preserves the REVEALED
  value (a `'**********'` mask appearing in encoded output = FAIL). A repo-audit
  grep (part of P2-8) forbids raw-payload retention fields (`this.raw = payload`
  style) in `packages/core/src/types/`.
- Coverage accounting: the sweep tallies occurrences per tag and asserts (i) every
  tag in the generated `corpus/contract/tag-universe.json` (see C3 generator; built
  by scanning the corpus + `types.py` exports) is registered, and (ii) every
  registered tag was exercised ≥1 time — a tag with zero corpus occurrences is
  reported (not failed) so authored vectors can be requested.
- Until P2-7 lands, the sweep runs with an explicit allowlist of not-yet-registered
  tags (the packet ordering in C10 shrinks it to empty); the allowlist lives in the
  test file and its emptiness is a P2-8 done-criterion.

**(b) Result-shape + entity-model golden tests** —
`packages/core/src/types/{results,entities}/*.golden.test.ts`:

- Source of goldens: wire vectors' `expect.result` payloads (the canonical Python
  to-dict shapes, extracted at record time) for each result-returning api, selected
  via a hand-maintained `api → result class` table (~40 rows for results, built from
  api-map.json signatures; the table itself is reviewed in the mini-audit).
- **Scope extension (entity models)**: the same mechanism covers the 125 Pydantic
  entity models — entity/data-governance wire vectors carry plain `expect.result`
  payloads (535/608 in `corpus/entities/` alone), mapped via an `api → entity
  model` table; models with no vector anywhere get an authored fixture or a named
  deferral row in `model-coverage.json` (C5 item 5). "Every type locked before
  anything consumes it" is only true WITH this extension.
- Test body per class: `fromDict(expect.result)` → `toJSON()` → canonical-diff
  against the original payload (identity through the class proves field coverage,
  optionality handling, and serializer shape without any client). `$type`-tagged
  values inside results (`datetime`, `bytes`) decode via the registry first.
- **Anti-vacuity (mandatory)**: identity-through-the-class alone is satisfiable by
  an echo implementation (store payload, return it). Every golden therefore adds a
  mutation probe: (i) inject an unknown key into the payload and assert the
  strict-decode error (for strict classes / `extra='forbid'` models), OR (ii) for
  lax models, assert `Object.keys(instance.toJSON())` equals a statically declared
  per-class field list (so an echo of the mutated payload fails). Combined with
  the sweep's `instanceof` check and the raw-payload audit grep, echo
  implementations cannot pass.
- Plus 1–2 hand-written construction goldens per class for the empty case
  (`toRows()` on empty data, `rowColumns()`).
- `toRows()` itself is NOT vector-lockable (pandas is excluded from recording — no
  `.df` vectors exist). Lock = translated unit tests from the Python `.df` tests
  (same fixtures, assert the rows list) — documented deferral of wire-level locking,
  compensated in C9 by an oracle check on `to_table_dict` equivalents where the
  Python registry exposes them (it does not today → stays a translated-test-only
  contract; recorded in the risk register).

**(c) Exception/code locks** — as specced in C3: registry-equality test against
`corpus/contract/error-codes.json` + guard-vector replay (the behavioral lock) +
translated error-shape tests.

**(d) Enum locks** — as specced in C2: snapshot equality against
`conformance/vectors/enums/bookmark_enums.json` and `corpus/contract/literal-aliases.json`.

**Explicitly NOT lockable in Phase 2 (deferrals, with owners):**

| Deferred | Why | Locked when |
|---|---|---|
| Wire serialization of entity *Params models into request bodies | needs api_client + entity clients | Phase 3 B4/B6 wire vectors (810 `api_client.*` + 833 `workspace.*`) |
| Result parsing from raw API response bodies (`given_response` → result) | parsing lives in services | Phase 3 B5/B6 |
| `toRows()` row shape | no `.df` vectors exist (pandas excluded at record time) | translated Layer-3 tests only (permanent), C8(b) note |
| `APIError` subclass HTTP-context fields (`statusCode`, `responseBody`, …) | only constructible from transport outcomes | Phase 3 B4 wire vectors + Layer-3 |
| `MixpanelApiError`/`MixpanelHttpError` (R5.1 client-tier) | Phase 3 B4 classes | B4 |
| resolver/`ActiveSession` persistence semantics, `BridgeFile` | node-side file I/O | Phase 3 B7/B8 Layer-3 tests |
| rrweb IntEnums + analyzer types | `_internal/replays`, batch B5 | B5 golden files |
| `V*/B*/U*/UP*` validator-code behavior | validators are batch B2 | B2 validation-error vectors (680) |
| TypedDicts (`QueryMeta` etc.) | compile-time only, no runtime artifact | tsc only (by design) |

## C9 R10.9 differential harness plan

Every Phase-2 packet runs a throwaway differential pass before review (R10.9), and
Phase 2 leaves behind one durable extension to the standing Layer-2 harness.

**Oracle entry points that exercise Phase-2 types** (the 40 `types.*` names in the
D4 recorder registry are callable through `oracle-py`'s `oracle.call` today; the 4
starred names below are NOT registered yet and become callable only after P2-1
adds them on the support branch):

- The 40 registered `types.*` entries: `types.Filter` (+ 11 factory statics: `on`,
  `before`, `since`, `in_the_last`, `in_the_next`, `not_in_the_last`,
  `date_between`, `date_not_between`, `in_cohort`, `not_in_cohort`,
  `list_contains`),
  `types.CohortCriteria.{did_event,did_not_do_event,has_property,in_cohort,not_in_cohort}`,
  `types.CohortDefinition{,.all_of,.any_of,.to_dict}`, `types.{CohortBreakdown,
  CohortMetric,Metric,Formula,GroupBy,TimeComparison,FrequencyBreakdown,
  FrequencyFilter,Exclusion,HoldingConstant,ListItemGroupMode,FlowStep,UserAction}`,
  `types.{Replay,ReplayBundle,ReplayEvent,ReplaySummary,SignedReplay}`,
  `types._sanitize_raw_cohort`.
- P2-1 additions (*): `types.FunnelStep`*, `types.RetentionEvent`*,
  `types.CohortCriteria.property_is_set`*,
  `types.CohortCriteria.property_is_not_set`* — total 44 entries once landed.
- **New protocol method `codec.roundtrip`** added to BOTH bridges (Python side on
  the `ts-port/phase2-contract-support` branch; `conformance/schema/oracle-protocol.md`
  gets a versioned addendum): `params: {value: <$type-tagged JSON>}` →
  `{ok: true, output: encode(decode(value))}`. This turns the codec table itself
  into a fuzzable cross-language surface: the harness generates random *instances*
  via strategies, encodes on one side, round-trips on the other, diffs.

**oracle-ts growth**: `differential/oracle/` registers the same 44 `types.*` apis
(reusing the conformance `bindings.ts` adapters — one registration module, imported
by both, so runner and oracle can never disagree) + `codec.roundtrip`. Everything
else keeps returning `UNPORTED` (counted as skip).

**Fuzz strategies**: reuse/vendor the suite's composite strategies per D14 — the
real files on `ts-port/phase1-addendum` are
`tests/test_types_{funnel,retention,flow,flow_tree}_pbt.py`,
`tests/test_cohort_definition_pbt.py`, `tests/test_cohort_behaviors_pbt.py`,
`tests/test_custom_property_pbt.py`, `tests/test_user_query_pbt.py` (NOT
`tests/test_query_types*.py`, which matches nothing; `tests/pbt/*` holds
account/session/resolver/config strategies for C4) — into
`conformance/differential/strategies.py` where imports entangle with fixtures. Every
generated corpus applies the **mandatory edge-case set** as explicit `@example`s:
integral float (`18.0`), fractional float (`1.5`), `True`, `None`, empty list,
empty string, non-BMP string (`"𝒳"`), and **every error branch** — for Phase 2 the
error branches are enumerable: one example per code in `CODED_GUARD_REGISTRY` that
belongs to a C7/C6-d family (the generator artifact gives the list; the harness
asserts both sides return `ok:false` with the same `{class, code}`).

**fast-check property list (TS-side unit PBT, colocated tests):**

1. `Secret` never leaks: for arbitrary strings s, `new Secret(s)` —
   `String(x)`, `${x}`, `JSON.stringify(x)`, `JSON.stringify({k: x})`,
   `x.toString()`, inspect-symbol call, `Object.entries(x)` flattening — none
   contain `s` (unless `s === '**********'`); `x.reveal() === s`.
2. Account-union exhaustiveness: for arbitrary valid variant payloads,
   `parseAccount` narrows to exactly one `type` and the canonical switch handles it
   (the `never` default is unreachable — property instruments a visited-arm set).
3. Codec identity: for arbitrary generated TS instances of each C7 class,
   `decode(encode(x))` is deep-equal to `x`; for arbitrary valid tagged JSON,
   `encode(decode(j))` canonical-equals `j`.
4. Guard totality: for arbitrary *invalid* inputs drawn per-guard, the thrown error
   is `instanceof ParamValidationError|ParamTypeError` AND `code ∈
   CODED_GUARD_REGISTRY ∪ TWIN_CODES` — never a bare `Error`/`TypeError`.
5. `coerce.ts` parity with R4.12 tables: `coerceInt` accepts `42`/`42.0`/`"42"`,
   rejects `42.5`/booleans; `coerceBool` accepts exactly the
   `true|t|yes|y|on|1` sets; `default_factory`-on-absent-only (absent vs
   explicit-null property).
6. `toJSON`/`fromDict` inverse on result classes for arbitrary valid field values.
7. Enum/alias tables: membership arrays contain no duplicates and match the union
   cardinality (compile-time check backstopped at runtime).

**Pass criterion for the Phase-2 differential gate (P2-9)**: oracle-py ↔ oracle-ts
green over all 44 `types.*` apis and `codec.roundtrip` for a fixed budget (≥500
examples per api family + the full edge set), zero unexplained divergences;
divergences file shrunken repros under `conformance/differential/repros/` and block
the packet.

## C10 Work breakdown (P2-1..P2-10)

Common done-criteria for every TS packet (restated once): `tsc --strict` clean per
package · packet tests green · applicable C8 vector-lock checks green · the 42
pre-existing PASS vectors still green · `npm run check` green · one local commit on
TS `main` (repo stays local, D16) with a message naming the packet. Python-side
packets: `just check` green (or the documented `conformance/`-scoped equivalent) ·
commit on `ts-port/phase2-contract-support`. No mutation testing anywhere [SA1].
R10.13: every build agent runs at effort ≤ high with the incremental-write protocol.

| Packet | Files to produce | Done-criteria beyond common | R10.10 call-site context (Phase-3 consumers, per api-map) | Depends on |
|---|---|---|---|---|
| **P2-1** Python contract generator + coverage closure | Branch `ts-port/phase2-contract-support` off `ts-port/phase1-addendum`; `conformance/contract/{__init__,generate_contract}.py` + tests; artifacts `error-codes.json`, `literal-aliases.json`, `tag-universe.json`, `model-coverage.json` (C5 item 5); **recorder-registry entries + recorded vectors for the 5 uncovered `types.*` entry points** (`FunnelStep`, `RetentionEvent`, `CohortCriteria.{did_not_do_event,property_is_set,property_is_not_set}`) incl. their guard-failure cases, re-extract + re-pin snapshot SHA (Risk #3 workflow); extend TS `scripts/sync-corpus.sh` + run it (TS commit) | Artifacts deterministic (re-run = byte-identical); tag-universe built by JSON-aware `$type` walk and verified against an independent JSON-aware scan (NOT grep — an escaped `\"$type\"` string payload yields a pseudo-tag); api-index `types.*` count = 44 after re-extract; Python runner + D9 drift check still green on the branch | consumed by C8 tests only | — |
| **P2-2** coerce + Secret + errors | `packages/core/src/{coerce,secret,invariant,errors}.ts`, `errors-codes.gen.ts` (generated from artifact by a checked-in script `scripts/gen-error-codes.mjs`) + tests (registry equality, error shapes, fast-check #1/#5) | C8(c) registry test green | `_handle_response`/retry (B4) raise these; validators (B2) raise coded errors; every entity client catches `MixpanelHeadlessError`; `Workspace.use` raises Config errors (B6/B7) | P2-1 |
| **P2-3** literals + enums + bookmark-enum tables | `types/literals.ts`, `types/enums.ts`, `bookmarks/enums.ts` + snapshot tests | C8(d) both locks green | option bags of all B5/B6 methods (`unit: TimeUnit`, …); B2/B3 validators consume `bookmarks/enums.ts` tables (`VALID_CHART_TYPES` membership via `.has()`) | P2-1 |
| **P2-4** auth model | `auth/{account,session,token,index}.ts` + parse factories + exhaustiveness/PBT tests + `OAuthTokens` codec registration | fast-check #2 green; codec sweep covers `SecretStr`/`OAuthTokens` tags | `resolve_session` (B7) returns `Session`; api_client (B4) consumes `accountAuthHeader` + `Session.headers`; node config/bridge (B8) parses accounts; `createXClient({getScope})` scope objects (R2.9) | P2-2 |
| **P2-5a** filter/metric/group core | `types/query-params/{filter,group-by,metric}.ts` (Filter+ListItemGroupMode+PropertyInput+CustomPropertyRef+InlineCustomProperty, GroupBy, Metric, CohortMetric, Formula, TimeComparison) + codecs + `bindings.ts` types.* adapters for these + guard tests | their `types.*` vectors (159 in the current snapshot) PASS; sweep allowlist shrinks accordingly | `workspace.build_params` (B6), `bookmark_builders.build_filter_entry/build_filter_section/build_group_section` (B3), `segfilter.build_segfilter_entry` (B3), `user_builders.filter_to_selector` (B2) all take these as inputs — R10.12 note: new-format `filterValue` stays JSON numbers | P2-2, P2-3 |
| **P2-5b** cohort family | `types/query-params/cohort.ts` (CohortCriteria, CohortDefinition, CohortBreakdown, `sanitizeRawCohort`) + codecs/bindings/guards | `types.CohortCriteria/CohortDefinition/CohortBreakdown/_sanitize_raw_cohort` vectors PASS (110 in the current snapshot + the P2-1 `did_not_do_event`/`property_is_set`/`property_is_not_set` additions) | `create_cohort/update_cohort` params flattening (B6), `CohortMetric` cross-refs, `bookmark_builders.build_flow_cohort_filter` (B3) | P2-5a |
| **P2-5c** funnel/retention/flow/frequency | `types/query-params/{funnel,retention,flow,frequency}.ts` (FunnelStep, Exclusion, HoldingConstant, RetentionEvent, FlowStep, FrequencyBreakdown, FrequencyFilter) + codecs/bindings/guards | their vectors PASS (66 in the current snapshot + the P2-1 `FunnelStep`/`RetentionEvent` additions); **R10.7 note: `FrequencyFilter` replicates current Python output byte-for-byte incl. the shape the live server 500s on (probe record `context/phase1/addendum/frequency-filter-probe.md`) — comment, do not fix** | `build_funnel_params`/`build_retention_params`/`build_flow_params` (B6/B3); FS1 session-event guard consumed by flows builders | P2-5a |
| **P2-6** result classes | `types/results/*.ts` (C6-a..d; UserAction lands here per C6-d) + golden tests + translated `.df`→`toRows` tests + codecs for `UserAction`/`Replay*`/`SignedReplay` tags | C8(b) goldens green for all classes with wire vectors; replay `types.*` vectors (~60) PASS | LiveQueryService/DiscoveryService (B5) construct these from parsed bodies; `workspace.*` (B6) returns them; replays service (B5) consumes `SignedReplay.expires_at` etc. | P2-2, P2-3 |
| **P2-7** entity models | `types/entities/*.ts` (125 models) + fromDict/toDict + codec registration of all `*Params`/entity tags + entity golden tests (C8b extension) + vendored cross-check files + **E4 alerts verification** (endpoint diff + PROVENANCE update) | codec-sweep allowlist EMPTY (the full `tag-universe.json` rich set — 80 tags in the current corpus — registered; no hard-coded count: the criterion is artifact-driven); every model accounted for in `model-coverage.json` (golden / authored fixture / named deferral row with owner); contract test-d files compile; E4 divergences recorded | entity client factories (B6) `create<Entity>Client` take `Create*/Update*Params` and return entity models; `paginateAll<T>` (B4) binds `PaginatedResponse`/`CursorPagination` | P2-2, P2-3, P2-4 (accounts.ts models) |
| **P2-8** corpus sweep finalization | `conformance-runner/test/codec-sweep.test.ts` in final form (no allowlist); **new module `conformance-runner/src/batch-status.ts`** (declarative api-prefix → pending/done map + verdict-path wiring + unit test — no such table exists today, see C7 item 4) flipped so `types.*` UNPORTED→FAIL for stragglers; raw-payload-retention audit grep (C8a/C8b anti-vacuity); conformance report checkpoint committed (counts: expected ≥ 395 + P2-1 additions + 42 PASS) | sweep green over all corpus lines (3,322 pre-P2-1; re-measured after re-pin); report JSON archived under `context/phase2/` in the Python repo | — | P2-5*, P2-6, P2-7 |
| **P2-9** differential gate | oracle-protocol addendum (`codec.roundtrip`, both repos); oracle-ts `types.*` surface; strategy vendoring; fuzz run per C9 budget; repros triaged | zero unexplained divergences; edge-set coverage list checked in | standing Layer-2 harness inherits the surface for Phase-3 nights | P2-8 (Python side can start after P2-1) |
| **P2-10** independent mini-audit | `context/phase2/audit/phase2-audit.md` (Python repo) | Fresh agent, no prior context, verifies: export coverage map over the **274 distinct** `__all__` names (each: ported / deferred-with-owner; the 10 duplicated alias strings key once); no weakened/dropped assertions in translated tests; `@internal` discipline vs published `.d.ts`; R3.9/R4.10/R4.11 spot-check on 10 random models; golden-table (C8b) completeness vs result-class list AND `model-coverage.json` vs the 125 entity models; guard-order parity on 5 sampled multi-guard constructors; all `TODO(port)` triaged; conformance report counts match P2-8 checkpoint | — | all |

Sequencing: P2-1 → {P2-2, P2-3} (parallel) → P2-4 ∥ P2-5a → {P2-5b, P2-5c, P2-6}
(parallel) → P2-7 → P2-8 → P2-9 → P2-10. Estimated TS volume: ~9–11k LOC source +
tests (Appendix-B B1's "~5,500 Python LOC" undercounts `types.py` reality — see
Discrepancy Log #6).

## Risk register (top 8)

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Guard-order divergence**: multi-guard Python constructors fire checks in source order; a TS port that reorders produces a *different* code for multi-invalid inputs, and vectors only lock the recorded single-fault cases | P2-5/P2-6 rule: transcribe guard blocks in source order, one comment per code; mini-audit samples 5 multi-guard constructors; C9 fuzz generates multi-invalid inputs and diffs `{class, code}` |
| 2 | **`exactOptionalPropertyTypes` mass friction**: 125 models × optional fields invite ad-hoc `?: T` (dropping `| undefined`) or `undefined`-assignments that break R3.9/R4.11 and the canonicalizer's null/absent distinction | The C4 optionality section is normative boilerplate; an ESLint custom-rule-free heuristic: codec sweep + golden tests catch the observable half; audit spot-checks the rest |
| 3 | **Vector-flip surprises**: turning 395 `types.*` vectors live may surface recorder artifacts (tuple/list, enum-value encoding, `_df_cache: null` payloads) that need PYTHON-side vector or codec fixes — sequencing risk back onto the support branch | Treat as R10.7 workflow: fix recorder/vectors on `ts-port/phase2-contract-support`, re-extract if needed, re-pin the snapshot SHA; budgeted in P2-5a as the first (largest) flip |
| 4 | **Codec round-trip false confidence**: canonical-diff normalizes numeric-string operand positions (R10.11) and sorts keys — a decode/encode bug that only reorders or renders numbers could hide | Sweep diffs the RAW subtree (no operand normalization — that rule is scoped to request-param positions, which Phase 2 never emits); lossless-JSON preserved tokens make `18.0`→`18` drift visible |
| 5 | **E4 alerts drift**: deriving alert types from wire vectors could still miss fields the vendored file has (server accepts more than Python sends) | E4 says Python IS the contract; unknown-field tolerance documented per model (`extra` behavior mirrors the Pydantic config per class); divergences logged in PROVENANCE for Phase-5 review |
| 6 | **`toRows()` contract is test-only** (no vectors, no oracle surface) — silent row-shape drift possible until a human consumes it | Translated `.df` tests copied assertion-for-assertion (R10.2, adversarial review) — one suite per `.df` body AND per auxiliary frame (`nodes_df`/`edges_df`/`trees_df`/`events_df`/`properties_df`/`relationships_df`); `rowColumns()` locked by the same tests; revisit adding a Python-side recordable `to_table_dict` registry entry in Phase 3 if drift appears |
| 7 | **Registry closure assumption**: Phase 2 assumes no new codes get minted while it runs; a concurrent Python change (new guard, new export) silently invalidates the artifacts | Artifacts carry `generated_from` SHA; the TS registry-equality test fails loudly on re-sync; sync-corpus refuses manifest drift already |
| 8 | **Scope bleed into B2/B3**: `types.py` guards sit next to builder logic (e.g. `Filter` selector interplay, `validate_*` twins); implementers may "helpfully" port adjacent builders without their vectors | Packet file lists are exhaustive; anything outside them is a `TODO(port)` + stop; mini-audit checks no unlisted public API appeared |

## Discrepancy log (repo reality vs plan/api-map/ground-state)

1. **api-map export counts are stale/mis-bucketed**: header says 281 exports; live
   `__all__` = 284 (the 3 addendum exception classes post-date the map). Category
   table says "140 literal aliases & enums" and "92 result/param types"; measured
   reality: 37 distinct Literal aliases + 8 Enums + 4 NewTypes + 1 union alias +
   1 const vs 59 dataclasses + 125 Pydantic models. Phase-2 sizing in this design
   uses the measured partition; the api-map remains authoritative only for *names*
   and Workspace-member batching.
2. **Vector totals**: ground-state brief says "3,155 vectors (42 PASS, 3,113
   UNPORTED)"; the snapshot manifest says `total: 3007` (extracted) and the corpus
   holds 3,322 JSONL lines including authored vectors. The design uses the measured
   numbers; the 3,155 figure matches no on-disk count I could reproduce (likely a
   prior runner report including some but not all authored bundles).
3. **R4.3 vs Python source**: R4.3's example names `BookmarkType` as a string enum,
   but Python defines it as a `Literal` alias and R4.3's own alias rule then
   applies. Resolved source-kind-wins (C2); flag for a rulebook editorial touch-up
   in the next amendment pass (do not amend mid-phase).
4. **codecs.py cosmetic**: the module docstring lists `CohortDefinition` in the
   `DATACLASS_CODECS` table, but the `_dataclass_codecs()` tuple omits it (it is
   special-cased via `_decode_cohort_definition`). No behavior impact; noted so the
   TS mirror doesn't "fix" it by table-izing.
5. **Tag universe ≫ D4.4 list**: the corpus carries 85 distinct `$type` tags — the
   D4.4 dataclass set plus ~50 Pydantic model tags (`CreateBookmarkParams`,
   `SchemaEntry`, `OAuthTokens`, …) handled Python-side by generic model lookup. C7's
   binding scope therefore covers ALL of them (via C5 classes), not just the 14-name
   list in the Phase-2 tasking prompt.
6. **Appendix-B B1 size**: "~5,500 Python LOC" — `types.py` alone is 13,938 LOC
   (docstring-heavy; ~40% of `__all__`'s implementation). Wall-clock estimates for
   Phase 2 should assume roughly 2× the plan's B1 weight.
7. **Manifest has no `parse` kind** in `by_kind` (`builder` 1,744 / `wire` 1,198 /
   `validation-error` 65): extracted parse coverage rides inside `wire` vectors'
   `expect.result`; standalone `parse` vectors exist only in the authored bundle
   (E1). C8(b) is designed around `expect.result`, so this changes nothing, but the
   plan's "~1,400 wire + parse" phrasing shouldn't be read as a separate extracted
   parse corpus.
8. **api-map internal totals disagree**: header says "205 public Workspace members /
   200 methods + 5 properties" while plan §4.2 says "205 sync Workspace methods".
   Cosmetic; Phase-3 queue consumers should use the JSON, not the prose.
9. **`__all__` duplicate entries (Python latent nit)**: 284 `__all__` strings but
   only 274 distinct — 10 Literal-alias names are listed twice (`MathType`,
   `PerUserAggregation`, `FunnelMathType`, `RetentionAlignment`, `RetentionMode`,
   `RetentionMathType`, `CustomPropertyType`, `FilterOperator`,
   `FilterPropertyType`, `FilterDateUnit`; e.g. `__init__.py:332` and `:573` for
   `MathType`). Do NOT fix mid-phase (would perturb the audited addendum surface);
   all Phase-2 artifacts, snapshot tests, and coverage maps key on distinct names.
   `BookmarkTypeLiteral` exists in `types.py` but is NOT exported — it gets no TS
   surface.
10. **Recorder-coverage holes closed by P2-1**: `types.FunnelStep` and
    `types.RetentionEvent` (real `__post_init__` guards, zero vectors, absent from
    the D4 registry), `types.CohortCriteria.did_not_do_event` (registered, zero
    vectors), and `CohortCriteria.property_is_set`/`property_is_not_set`
    (unregistered public factories). Pre-fix, earlier drafts of this design claimed
    vector/oracle locks for these — corrected; the locks exist only after P2-1's
    additions land and the snapshot is re-pinned.

## Escalations

None. The two standing rulings this phase leans on are already decided and are
honored as-is: **E4** (alerts contract = whatever Python maps to; vendored file
advisory — implemented as the P2-7 verification step) and **R10.7 frequency-filter
posture** (TS replicates `build_frequency_filter_entry`'s current byte-for-byte
behavior including the server-500 shape; no fix designed). The C2 `BookmarkType`
representation call and the NewType-as-plain-alias call are design-level
interpretations within the rulebook's delegated authority and are recorded in the
Discrepancy Log rather than escalated.
