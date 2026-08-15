# Coding-Pass Design — Uncoded-Raise Registry Codes (E2 / R5.5)

- Task: AD-0 (addendum workflow). Branch: `ts-port/phase1-addendum`, based on
  `ts-port/phase1-verification-rig` @ `852d718` (verified rig HEAD at design time).
- Authority: user ruling **E2** (`context/phase1/design/escalation-resolutions.md`) —
  the sanctioned Python-side coding pass under rulebook **R10.7**; gate-verdict
  recommendation **R1** (`context/phase1/audit/GATE-VERDICT.md` §8) sets the
  vector-yield expectation (≥2 recordable tests per site).
- Inputs of record: `context/phase1/recon/validation-errors.json` (`uncoded_sites`,
  `family_label_mapping`, `assertion_styles`), `conformance/vectors/manifest.json`
  (`exclusion_details.uncoded_raise` — the 14-test worklist; `exclusions.uncoded_raise=14`),
  fresh greps at `852d718` (145 raw `raise ValueError|TypeError` hits in the six
  in-scope modules; see §1), `conformance/record/{emit,plugin,registry}.py` (§5),
  `src/mixpanel_headless/exceptions.py` (§2). Operative vector schema:
  `conformance/schema/vector.schema.json`.
- Hard constraints: STRICT TDD, mypy --strict, ruff, full docstrings, coverage ≥90,
  `just check` green before every commit; `CLAUDE.md`, `.claude/`, `pyproject.toml`
  untouched; src/ changes only as this design mandates; local commits only.
- Behavior lock (R10.7): the coding pass changes **exception class and adds `.code`**;
  it must NOT change which inputs raise, message text, or any success-path output.
  Every touched guard keeps its exact predicate and message string.

---

## 1. SITE INVENTORY

Fresh grep at `852d718` over the pure-builder scope (plus the two worklist-implicated
impure modules) finds **145 raw `raise ValueError`/`raise TypeError` statements**:

| Module | Raw sites | In coding scope | Notes |
|---|---|---|---|
| `src/mixpanel_headless/types.py` | 104 | 98 | 6 pydantic-internal sites stay builtin (policy P3, §2) |
| `src/mixpanel_headless/_internal/query/user_builders.py` | 13 | 13 | engage selector dialect |
| `src/mixpanel_headless/workspace.py` | 9 | 9 | facade arg guards (pure pre-flight) |
| `src/mixpanel_headless/_internal/bookmark_builders.py` | 8 | 8 | 2 are TypeError |
| `src/mixpanel_headless/_internal/api_client.py` | 7 | 6 | `_get_auth_header:411` excluded (`pragma: no cover` Literal-exhaustiveness guard, unreachable) |
| `src/mixpanel_headless/_internal/segfilter.py` | 4 | 4 | segmentation where-expression builder |
| `src/mixpanel_headless/_internal/expressions.py` | 0 | 0 | no raise sites (recon-confirmed) |
| `src/mixpanel_headless/_internal/transforms.py` | 0 | 0 | no raise sites (recon-confirmed) |
| `src/mixpanel_headless/_internal/query/` (others) | 0 | 0 | `user_validators.py` already fully coded |
| **Total** | **145** | **138** | |

Plus the **response-side pydantic seams** (no `raise` keyword; `model_validate`
propagates `pydantic.ValidationError`) implicated by 3 of the 14 manifest worklist
tests — wired in B3 via `RESPONSE_VALIDATION_ERROR` (§1.7).

Reconciliation with recon `uncoded_sites` (104+13+9+8+4 = 138 across its five files):
identical scope; the delta in this table is api_client (recon listed it implicitly via
the manifest worklist, not in `uncoded_sites`) and the exhaustiveness-guard exclusion.

Code-minting conventions used below (consistent with the R5.3 registry style —
`FAMILY``N``_SNAKE_GIST`; same-number variants precedented by `F1_MAX_STEPS`/`F1_MIN_STEPS`;
several sites may share one code when they enforce the same rule, precedented by
`_validate_cohort_args` serving three call families):

- **Twin reuse**: where a fail-fast constructor guard duplicates an already-coded
  validator rule (the documented `CM5` dual-enforcement pattern,
  validation-errors.json `family_label_mapping`), the guard carries the **same full
  code** as its validator twin (marked "twin" below). Implementer verifies rule-identity
  before reuse; if predicates differ, mint the listed fallback instead.
- **Docstring/comment labels are binding** where they exist: `CF1/CF2`, `CB1/CB2`,
  `CM1/CM2/CM5`, `CD1–CD9`, `CA1/CA2`, `TC0–TC3b`, `FB1–FB4`, `FF1–FF5`, `FS1`.
- New families minted here: `TC` `FM` `LC` `FD` `LG` `GB` `EV` `MT` `EX` `HC` `AT`
  `RS` `SR` `UA` `RE` `RP` `RB` `ES` `BB` `SG` `WS` `WR` `AC`, plus full codes for the
  label families `CF` `CB` `CM` `CD` `CA` `FB` `FF` `FS` (no minted full-code string
  collides with the 175 existing registry codes — checked against recon `codes`;
  prefix overlap with `CB3_…`/`CM5_…` is intentional label continuation).
- Generic codes per R5.5: `VALIDATION_ERROR` (param/construction pydantic paths — note
  it is already the `ValidationError` dataclass default, exceptions.py:1191) and
  `RESPONSE_VALIDATION_ERROR` (response `model_validate` paths). Minted once, wired in B3.

Line numbers are at `852d718`; implementer re-verifies each before editing.

### 1.1 `types.py` — cohort/metric/breakdown families (B1)

| Site | Exc | Message gist | CODE |
|---|---|---|---|
| types.py:8992 `_validate_cohort_args` | ValueError | "cohort must be a positive integer" | `CF1_COHORT_ID_NOT_POSITIVE` / `CB1_…` / `CM1_…` per caller family (see note) |
| types.py:8994 `_validate_cohort_args` | ValueError | "cohort name must be non-empty when provided" | `CF2_COHORT_NAME_EMPTY` / `CB2_…` / `CM2_…` per caller family |
| types.py:9284 `CohortMetric.__post_init__` | ValueError | "does not support inline CohortDefinition" | `CM5_INLINE_COHORT_METRIC` (**twin** — dual enforcement documented in recon; identical code string as validation.py:1978) |
| types.py:9063 `CohortDefinition.__post_init__` | ValueError | "requires at least one criterion" | `CD9_EMPTY_CRITERIA` |
| types.py:9084 `CohortDefinition.all_of` | ValueError | same rule | `CD9_EMPTY_CRITERIA` |
| types.py:9107 `CohortDefinition.any_of` | ValueError | same rule | `CD9_EMPTY_CRITERIA` |

Note — `_validate_cohort_args` serves three families (docstring labels: `Filter.in_cohort`
/`not_in_cohort` → CF; `CohortBreakdown.__post_init__` → CB; `CohortMetric.__post_init__`
→ CM). Implementation: add a `family: str` parameter (`"CF" | "CB" | "CM"`) passed by each
caller; the two raise sites format the code from it. Six distinct full codes, two sites.

### 1.2 `types.py` — CohortCriteria / cohort helpers (B1)

| Site | Exc | Message gist | CODE |
|---|---|---|---|
| types.py:8608 `CohortCriteria` (performed/…) | ValueError | "event name must be non-empty" (# CD4) | `CD4_EMPTY_EVENT` |
| types.py:8612 | ValueError | "aggregation and aggregation_property must both be set or both None" (# CA1/CA2) | `CA1_AGGREGATION_PAIR` |
| types.py:8617 | ValueError | "aggregation_property must be a non-empty string" | `CA2_EMPTY_AGGREGATION_PROPERTY` |
| types.py:8627 | ValueError | "exactly one of at_least, at_most, exactly" (# CD1) | `CD1_FREQUENCY_PARAM_REQUIRED` |
| types.py:8633 | ValueError | "frequency value must be >= 0" (# CD2) | `CD2_FREQUENCY_NEGATIVE` |
| types.py:8653, 8658, 8663 | ValueError | "exactly one time constraint required" (# CD3; 3 sites, 1 rule) | `CD3_TIME_CONSTRAINT_REQUIRED` |
| types.py:8697 | ValueError | "time window value must be positive" | `CD3_WINDOW_NOT_POSITIVE` |
| types.py:8711 | ValueError | "from_date requires to_date" (# CD5) | `CD5_FROM_REQUIRES_TO` |
| types.py:8713 | ValueError | "to_date requires from_date" | `CD5_TO_REQUIRES_FROM` |
| types.py:8719 | ValueError | dates YYYY-MM-DD (# CD6; delegates to `_validate_cohort_date`) | `CD6_DATE_FORMAT` |
| types.py:8726 | ValueError | "from_date must be before or equal to to_date" | `CD6_DATE_ORDER` |
| types.py:8823 `CohortCriteria` (property criteria) | ValueError | "property name must be non-empty" (# CD7) | `CD7_EMPTY_PROPERTY` |
| types.py:8889 `CohortCriteria.in_cohort` | ValueError | "cohort_id must be a positive integer" (CD8) | `CD8_COHORT_ID_NOT_POSITIVE` |
| types.py:8917 `CohortCriteria.not_in_cohort` | ValueError | same rule (CD8) | `CD8_COHORT_ID_NOT_POSITIVE` |
| types.py:8444 `_validate_cohort_date` | ValueError | "dates must be YYYY-MM-DD format" | `CD6_DATE_FORMAT` |
| types.py:8448 `_validate_cohort_date` | ValueError | "correct format but is not a valid calendar date" | `CD6_DATE_INVALID` |
| types.py:8484 `_build_event_selector` | ValueError | "unsupported filter operator for cohort selector" | `CD10_UNSUPPORTED_FILTER_OPERATOR` |

### 1.3 `types.py` — query-builder dataclass guards (B1)

| Site | Exc | Message gist | CODE |
|---|---|---|---|
| types.py:6832 `TimeComparison.__post_init__` | ValueError | invalid type (# TC0) | `TC0_INVALID_TYPE` |
| types.py:6839 | ValueError | relative requires unit (# TC1) | `TC1_REQUIRES_UNIT` |
| types.py:6846 | ValueError | invalid unit (# TC1b) | `TC1B_INVALID_UNIT` |
| types.py:6851 | ValueError | relative rejects date | `TC1_REJECTS_DATE` |
| types.py:6858 | ValueError | absolute requires date (# TC2) | `TC2_REQUIRES_DATE` |
| types.py:6863 | ValueError | absolute rejects unit | `TC2_REJECTS_UNIT` |
| types.py:6869 | ValueError | date must be YYYY-MM-DD (# TC3) | `TC3_DATE_FORMAT` |
| types.py:6879 | ValueError | not a valid calendar date (# TC3b) | `TC3B_DATE_INVALID` |
| types.py:7035 `Metric.__post_init__` | ValueError | math requires property | `V13_METRIC_MATH_PROPERTY` (**twin** — recon: "V13 fail-fast") |
| types.py:7041 | ValueError | percentile requires percentile_value | `V26_PERCENTILE_REQUIRES_VALUE` (**twin** candidate; fallback `MT1_PERCENTILE_REQUIRES_VALUE`) |
| types.py:7049 | ValueError | invalid segment_method | `MT2_INVALID_SEGMENT_METHOD` |
| types.py:7104 `Formula.__post_init__` | ValueError | expression must be non-empty string | `FM1_EMPTY_EXPRESSION` |
| types.py:7179 `Filter.__post_init__` | ValueError | list_contains requires _list_item_filters | `LC1_MISSING_ITEM_FILTERS` |
| types.py:7184 `Filter.__post_init__` | ValueError | list_contains requires _list_item_quantifier | `LC2_MISSING_QUANTIFIER` |
| types.py:7761 `Filter._validate_date` | ValueError | "Date must be YYYY-MM-DD format" | `V8_DATE_FORMAT` (**twin**) |
| types.py:7765 `Filter._validate_date` | ValueError | "not a valid calendar date" | `V8_DATE_INVALID` (**twin**) |
| types.py:7912 `Filter.in_the_last` | ValueError | quantity must be positive | `FD1_QUANTITY_NOT_POSITIVE` |
| types.py:7947 `Filter.not_in_the_last` | ValueError | same rule | `FD1_QUANTITY_NOT_POSITIVE` |
| types.py:7984 `Filter.date_between` | ValueError | from_date must be before to_date | `FD2_DATE_ORDER` |
| types.py:8027 `Filter.date_not_between` | ValueError | same rule | `FD2_DATE_ORDER` |
| types.py:8068 `Filter.in_the_next` | ValueError | quantity must be positive | `FD1_QUANTITY_NOT_POSITIVE` |
| types.py:8157 `Filter.list_contains` | ValueError | pass either positional Filters or kwargs | `LC3_MIXED_ARGS` |
| types.py:8162 | ValueError | quantifier must be 'any' or 'all' | `LC4_INVALID_QUANTIFIER` |
| types.py:8168 | ValueError | kwarg keys must be non-empty strings | `LC5_EMPTY_KWARG_KEY` |
| types.py:8172 | **TypeError** | kwarg value must be str or … | `LC6_KWARG_VALUE_TYPE` |
| types.py:8184 | ValueError | requires at least one inner condition | `LC7_NO_CONDITIONS` |
| types.py:8189 | ValueError | no nested list_contains | `LC8_NESTED_LIST_CONTAINS` |
| types.py:8242 `ListItemGroupMode.__post_init__` | ValueError | sub must be non-empty string | `LG1_EMPTY_SUB` |
| types.py:8244 | ValueError | sub_type must be one of … | `LG2_INVALID_SUB_TYPE` |
| types.py:8319 `GroupBy.__post_init__` | ValueError | property must be non-empty string | `GB1_EMPTY_PROPERTY` |
| types.py:8321 | ValueError | bucket_size must be positive | `V12_BUCKET_SIZE_POSITIVE` (**twin** candidate; fallback `GB2_BUCKET_SIZE_NOT_POSITIVE`) |
| types.py:8329 | ValueError | bucket_min must be less than bucket_max | `V18_BUCKET_ORDER` (**twin** candidate; fallback `GB3_BUCKET_ORDER`) |
| types.py:8338 | ValueError | list_item incompatible with bucketing | `GB4_LIST_ITEM_BUCKETING` |
| types.py:8340 | ValueError | list_item requires plain str property | `GB5_LIST_ITEM_PROPERTY_TYPE` |
| types.py:8972 `_validate_event_name` | ValueError | "{class}.event must be a non-empty string" | `EV1_EMPTY_EVENT` |
| types.py:8974 `_validate_event_name` | ValueError | event contains control characters | `EV2_CONTROL_CHAR_EVENT` |
| types.py:9350 `FrequencyBreakdown.__post_init__` | ValueError | event non-empty (# FB1) | `FB1_EMPTY_EVENT` |
| types.py:9353 | ValueError | bucket_size positive (# FB2) | `FB2_BUCKET_SIZE_NOT_POSITIVE` |
| types.py:9359 | ValueError | bucket_min non-negative (# FB4) | `FB4_BUCKET_MIN_NEGATIVE` |
| types.py:9365 | ValueError | bucket_min < bucket_max (# FB3) | `FB3_BUCKET_ORDER` |
| types.py:9450 `FrequencyFilter.__post_init__` | ValueError | event non-empty (# FF1) | `FF1_EMPTY_EVENT` |
| types.py:9454 | ValueError | operator must be one of … (# FF2) | `FF2_INVALID_OPERATOR` |
| types.py:9460 | ValueError | value non-negative (# FF3) | `FF3_VALUE_NEGATIVE` |
| types.py:9467 | ValueError | date_range_value/unit both or neither (# FF4) | `FF4_DATE_RANGE_PAIR` |
| types.py:9475 | ValueError | date_range_value positive when set (# FF5) | `FF5_DATE_RANGE_VALUE_NOT_POSITIVE` |
| types.py:9902 `Exclusion.__post_init__` | ValueError | from_step >= 0 | `EX1_FROM_STEP_NEGATIVE` |
| types.py:9904 | ValueError | to_step >= from_step | `EX2_STEP_ORDER` |
| types.py:9954 `HoldingConstant.__post_init__` | ValueError | property non-empty | `HC1_EMPTY_PROPERTY` |
| types.py:10443 `FlowStep.__post_init__` | ValueError | forward in 0–5 | `FL3_FORWARD_RANGE` (**twin** candidate; fallback `FS2_FORWARD_RANGE`) |
| types.py:10447 | ValueError | reverse in 0–5 | `FL4_REVERSE_RANGE` (**twin** candidate — code exists in registry; fallback `FS3_REVERSE_RANGE`) |
| types.py:10456 | ValueError | session_event consistency (# FS1) | `FS1_SESSION_EVENT_MISMATCH` |
| types.py:4921 `CreateCustomEventParams._validate_alternatives` | ValueError | empty/whitespace alternatives | **P3 — stays builtin** (pydantic `@field_validator`; surfaces as `VALIDATION_ERROR` via B3 wiring) |
| types.py:4925 | ValueError | alternatives must be unique | **P3 — stays builtin** |
| types.py:5546, 5550, 5554, 5558 `CreateCustomPropertyParams._validate_formula_behavior` | ValueError | formula/behavior consistency | **P3 — stays builtin** (pydantic `@model_validator`; twin candidates in the coded `CP*` family noted for the implementer) |

Rationale for P3: raising a non-`ValueError` inside a pydantic validator escapes
pydantic's wrap contract; raising a `ValueError` subclass gets wrapped into
`pydantic.ValidationError` and the `.code` is lost either way. These 6 sites keep the
builtin raise; their contract is the generic `VALIDATION_ERROR` boundary (§1.7).

### 1.4 `types.py` — result/replay-model invariants (B1)

Constructed from wire data (replay/auth surfaces); coded for completeness, low direct
vector yield (§5).

| Site | Exc | Message gist | CODE |
|---|---|---|---|
| types.py:12206 `AccountTestResult._ok_iff_no_error` | ValueError | ok=True implies error None | `AT1_OK_IMPLIES_NO_ERROR` |
| types.py:12208 | ValueError | ok=False requires error | `AT2_NOT_OK_REQUIRES_ERROR` |
| types.py:12210 | ValueError | error_code/details only with error | `AT3_ERROR_FIELDS_ORPHANED` |
| types.py:12352 `ReplaySummary.__post_init__` | ValueError | replay_id non-empty | `RS1_EMPTY_REPLAY_ID` |
| types.py:12354 | ValueError | project_id positive | `RS2_PROJECT_ID_NOT_POSITIVE` |
| types.py:12356 | ValueError | start_time positive unix ms | `RS3_START_TIME_NOT_POSITIVE` |
| types.py:12361 | ValueError | retention_days in {1,7,30,90} | `RS4_INVALID_RETENTION_DAYS` |
| types.py:12447 `SignedReplay.__post_init__` | ValueError | url must end with '/' | `SR1_URL_NO_TRAILING_SLASH` |
| types.py:12451 | ValueError | query_string non-empty | `SR2_EMPTY_QUERY_STRING` |
| types.py:12453 | ValueError | env 'prod' or 'dev' | `SR3_INVALID_ENV` |
| types.py:12455 | ValueError | signed_at non-negative | `SR4_SIGNED_AT_NEGATIVE` |
| types.py:12552 `UserAction.__post_init__` | ValueError | timestamp positive unix ms | `UA1_TIMESTAMP_NOT_POSITIVE` |
| types.py:12556 | ValueError | target_desc non-empty | `UA2_EMPTY_TARGET_DESC` |
| types.py:12605 `ReplayEvent.__post_init__` | ValueError | replay_id non-empty | `RE1_EMPTY_REPLAY_ID` |
| types.py:12607 | ValueError | event_name non-empty | `RE2_EMPTY_EVENT_NAME` |
| types.py:12609 | ValueError | event_time positive unix seconds | `RE3_EVENT_TIME_NOT_POSITIVE` |
| types.py:12758 `Replay.__post_init__` | ValueError | replay_id non-empty | `RP1_EMPTY_REPLAY_ID` |
| types.py:12760 | ValueError | project_id positive | `RP2_PROJECT_ID_NOT_POSITIVE` |
| types.py:12762 | ValueError | start_time positive unix ms | `RP3_START_TIME_NOT_POSITIVE` |
| types.py:12767 | ValueError | end_time >= start_time | `RP4_TIME_ORDER` |
| types.py:12772 | ValueError | retention_days in {1,7,30,90} | `RP5_INVALID_RETENTION_DAYS` |
| types.py:13067 `ReplayBundle.__post_init__` | ValueError | project_id mismatch across replays | `RB1_PROJECT_ID_MISMATCH` |

### 1.5 `bookmark_builders.py` + `segfilter.py` (B2)

| Site | Exc | Message gist | CODE |
|---|---|---|---|
| bookmark_builders.py:395 `build_group_section` | **TypeError** | group_by elements must be str/GroupBy/CohortBreakdown/… | `BB1_GROUP_BY_ELEMENT_TYPE` |
| bookmark_builders.py:609 `build_flow_property_filter` | ValueError | requires at least one filter | `BB2_FLOW_PROPERTY_FILTER_EMPTY` |
| bookmark_builders.py:621 `build_flow_property_filter` | **TypeError** | only supports string property | `BB3_FLOW_PROPERTY_FILTER_TYPE` |
| bookmark_builders.py:673 `build_flow_cohort_filter` | ValueError | only accepts cohort filters | `BB4_FLOW_COHORT_FILTER_TYPE` |
| bookmark_builders.py:680 `build_flow_cohort_filter` | ValueError | single cohort filter, got N | `BB5_FLOW_MULTIPLE_COHORT_FILTERS` |
| bookmark_builders.py:689 `build_flow_cohort_filter` | ValueError | "Internal error: _value must be non-empty list" | `BB6_COHORT_VALUE_NOT_LIST` |
| bookmark_builders.py:696 `build_flow_cohort_filter` | ValueError | "Internal error: _value[0] not a dict" | `BB7_COHORT_VALUE_NOT_DICT` |
| bookmark_builders.py:703 `build_flow_cohort_filter` | ValueError | "Internal error: missing 'cohort' key" | `BB8_COHORT_KEY_MISSING` |
| segfilter.py:143 `_build_string_filter` | ValueError | unknown string operator | `SG1_UNKNOWN_STRING_OPERATOR` |
| segfilter.py:172 `_build_number_filter` | ValueError | unknown number operator | `SG2_UNKNOWN_NUMBER_OPERATOR` |
| segfilter.py:227 `_build_datetime_filter` | ValueError | unknown datetime operator | `SG3_UNKNOWN_DATETIME_OPERATOR` |
| segfilter.py:299 `build_segfilter_entry` | ValueError | unsupported property type | `SG4_UNSUPPORTED_PROPERTY_TYPE` |

(`expressions.py` and `transforms.py` have zero raise sites — B2's file list includes
them only to record that fact.)

### 1.6 `user_builders.py` + `workspace.py` + `api_client.py` guards (B3)

| Site | Exc | Message gist | CODE |
|---|---|---|---|
| user_builders.py:54 `_prop_ref` | ValueError | selector requires string property name | `ES1_PROPERTY_NOT_STRING` |
| user_builders.py:113 `filter_to_selector` | ValueError | expected list for 'equals' | `ES2_EQUALS_EXPECTS_LIST` |
| user_builders.py:129 | ValueError | equals produced no valid terms | `ES3_EQUALS_NO_TERMS` |
| user_builders.py:139 | ValueError | expected list for 'does not equal' | `ES4_NOT_EQUALS_EXPECTS_LIST` |
| user_builders.py:155 | ValueError | not_equals produced no valid terms | `ES5_NOT_EQUALS_NO_TERMS` |
| user_builders.py:165 | ValueError | expected str for 'contains' | `ES6_CONTAINS_EXPECTS_STR` |
| user_builders.py:172 | ValueError | expected str for 'does not contain' | `ES7_NOT_CONTAINS_EXPECTS_STR` |
| user_builders.py:179 | ValueError | expected number for 'is greater than' | `ES8_GT_EXPECTS_NUMBER` |
| user_builders.py:186 | ValueError | expected number for 'is less than' | `ES9_LT_EXPECTS_NUMBER` |
| user_builders.py:193 | ValueError | expected list of length 2 for 'is between' | `ES10_BETWEEN_EXPECTS_PAIR` |
| user_builders.py:198 | ValueError | lower bound not number | `ES11_BETWEEN_LOWER_NOT_NUMBER` |
| user_builders.py:202 | ValueError | upper bound not number | `ES12_BETWEEN_UPPER_NOT_NUMBER` |
| user_builders.py:219 | ValueError | unsupported filter operator | `ES13_UNSUPPORTED_OPERATOR` |
| workspace.py:312 `_check_event_properties_count` | ValueError | at most 5 event_properties | `WR1_TOO_MANY_EVENT_PROPERTIES` |
| workspace.py:334 `_validate_limit` | ValueError | limit below minimum | `WR2_LIMIT_TOO_SMALL` |
| workspace.py:336 `_validate_limit` | ValueError | limit above maximum | `WR3_LIMIT_TOO_LARGE` |
| workspace.py:444 `Workspace.__init__` | ValueError | target= mutually exclusive with axes | `WS1_TARGET_MUTUALLY_EXCLUSIVE` |
| workspace.py:590 `Workspace.use` | ValueError | same rule | `WS1_TARGET_MUTUALLY_EXCLUSIVE` |
| workspace.py:9978 `Workspace._validate_level` | ValueError | level 'organization' or 'project' | `WS2_INVALID_LEVEL` |
| workspace.py:10425 `Workspace.list_replays` | ValueError | exactly one of distinct_id/replay_ids (neither) | `WR4_REPLAY_SELECTOR_REQUIRED` |
| workspace.py:10429 `Workspace.list_replays` | ValueError | exactly one of distinct_id/replay_ids (both) | `WR4_REPLAY_SELECTOR_REQUIRED` |
| workspace.py:10434 `Workspace.list_replays` | ValueError | distinct_id requires from_date/to_date | `WR5_DATE_RANGE_REQUIRED` |
| api_client.py:1249 `MixpanelAPIClient.app_request` | ValueError | json_body/form_body mutually exclusive | `AC1_BODY_MUTUALLY_EXCLUSIVE` |
| api_client.py:2000 `export_profiles` | ValueError | distinct_id/distinct_ids mutually exclusive | `AC2_DISTINCT_ID_CONFLICT` |
| api_client.py:2006 | ValueError | behaviors/cohort_id mutually exclusive | `AC3_BEHAVIORS_COHORT_CONFLICT` |
| api_client.py:2012 | ValueError | include_all_users requires cohort_id | `AC4_INCLUDE_ALL_USERS_REQUIRES_COHORT` |
| api_client.py:2019 | ValueError | behaviors must be a list | `AC5_BEHAVIORS_NOT_LIST` |
| api_client.py:2027 | ValueError | as_of_timestamp cannot be in future | `AC6_AS_OF_TIMESTAMP_FUTURE` |
| api_client.py:411 `_get_auth_header` | TypeError | Literal-exhaustiveness guard | **EXCLUDED** (`pragma: no cover`, unreachable under mypy --strict) |

Note on `workspace.py:9170`'s existing `except ValueError` → `BookmarkValidationError`
(`code="U_FILTER"`) wrap around `filters_to_selector`: unchanged by this pass. Under the
§2 policy the new `ES*`-coded errors still `isinstance(ValueError)`, so the facade wrap
keeps firing exactly as today; direct calls to `filter_to_selector`/`filters_to_selector`
(the registered seams) surface the `ES*` codes. Same for
`user_validators.py:467`'s `except (ValueError, TypeError, RuntimeError)` → `U24` wrap
around `CohortDefinition.to_dict()` — subclassing preserves that behavior byte-for-byte.

### 1.7 Response-side pydantic seams (B3 — `RESPONSE_VALIDATION_ERROR`)

The 3 manifest-worklist tests that are not builtin-raise sites:

| Seam | Worklist test | CODE |
|---|---|---|
| `workspace.py` `create_dashboard` response `model_validate` | `tests/unit/test_workspace_crud_edge.py::TestEmptyResponseHandling::test_create_dashboard_empty_response_raises` | `RESPONSE_VALIDATION_ERROR` |
| `workspace.py` `get_bookmark` response `model_validate` | `…::test_get_bookmark_empty_response_raises` | `RESPONSE_VALIDATION_ERROR` |
| `api_client.py` `list_workspaces` response `model_validate` | `tests/unit/test_app_api_client.py::TestListWorkspacesEdgeCases::test_list_workspaces_missing_required_fields` | `RESPONSE_VALIDATION_ERROR` |

Implementation: one private helper (e.g. `_validate_response_model(model, payload, *,
endpoint)`) that wraps `pydantic.ValidationError` in the new `ResponseValidationError`
(§2) carrying `code="RESPONSE_VALIDATION_ERROR"` and `details={"model": …,
"errors": e.errors(include_url=False)}`. B3 applies it to the CRUD response-parsing
seams these three tests exercise, then sweeps the remaining `model_validate` response
call sites in `workspace.py`/`api_client.py` mechanically (same helper, TDD per seam
family — one test pair per swept method family, not per call site).

### 1.8 Worklist cross-check (manifest → sites)

All 14 `exclusion_details.uncoded_raise` tests map onto §1 sites:

| Worklist test | Site(s) |
|---|---|
| test_build_cohort_params …flow_multiple_cohort_filters | bookmark_builders.py:680 (`BB5`) |
| test_query_user_edge_cases t2_05 / t2_06 / t2_07 | user_builders.py:219 / 113 / 193 (`ES13`/`ES2`/`ES10`) |
| test_user_builders string_lower/upper_bound_rejected | user_builders.py:198 / 202 (`ES11`/`ES12`) |
| test_user_builders not_equals error_references_method | user_builders.py:155 (`ES5`) |
| test_segfilter unknown_{operator,number,datetime,property_type} | segfilter.py:143/172/227/299 (`SG1–SG4`) |
| test_app_api_client list_workspaces_missing_required_fields | §1.7 (`RESPONSE_VALIDATION_ERROR`) |
| test_workspace_crud_edge create_dashboard/get_bookmark empty | §1.7 (`RESPONSE_VALIDATION_ERROR`) |

---

## 2. EXCEPTION-CLASS POLICY

### Current hierarchy facts (exceptions.py at 852d718)

- `MixpanelHeadlessError(Exception)` carries `.code`/`.message`/`.details` +
  `to_dict()`. **No existing domain error subclasses `ValueError` or `TypeError`** —
  every class in the hierarchy inherits `Exception` only (verified by reading all 28
  class statements).
- `BookmarkValidationError(MixpanelHeadlessError)` requires a `Sequence[ValidationError]`
  and self-derives message/code — wrong constructor shape for single-guard raises.
- `ValidationError` (dataclass, not an exception) already defaults
  `code="VALIDATION_ERROR"`.
- Test surface at HEAD (recon `assertion_styles` + fresh count, identical numbers):
  **227 `pytest.raises(ValueError)`** occurrences (208 with same-line `match=`),
  **7 `pytest.raises(TypeError)`**, 124 `pytest.raises(pydantic.ValidationError)`.
  Zero exact-type assertions (`excinfo.type is ValueError` etc. — fresh grep: none).

### Options considered

1. **Raise existing domain errors (e.g. `BookmarkValidationError`)** — breaks every
   `pytest.raises(ValueError)` test that hits a converted guard (≈38 in pure-builder
   test files alone, up to 227 suite-wide incl. live tests), plus silently changes the
   behavior of the two in-src `except ValueError` wrap sites (workspace.py:9170 U_FILTER,
   user_validators.py:467 U24) — the wrapped codes would stop firing. Rejected.
2. **Keep builtins, attach `.code` by assignment** (`err = ValueError(...); err.code = …`)
   — no class-name contract for R5.2, invisible to `_encode_error` (which keys on
   `MixpanelHeadlessError`), mypy-hostile. Rejected.
3. **CHOSEN — new dual-inheritance domain errors:**

```python
class ParamValidationError(MixpanelHeadlessError, ValueError):
    """A builder/facade argument guard rejected a value (registry-coded)."""

class ParamTypeError(MixpanelHeadlessError, TypeError):
    """A builder/facade argument guard rejected a value's type (registry-coded)."""

class ResponseValidationError(MixpanelHeadlessError):
    """An API response failed Pydantic model validation (RESPONSE_VALIDATION_ERROR)."""
```

- `ParamValidationError` replaces every in-scope `raise ValueError(msg)` with
  `raise ParamValidationError(msg, code="<SITE CODE>")` — message strings byte-identical.
- `ParamTypeError` covers the 3 in-scope TypeError sites (types.py:8172,
  bookmark_builders.py:395, 621).
- `ResponseValidationError` wraps pydantic response failures (§1.7); raised
  `from exc` so the pydantic error stays chained.
- All three are exported from `__init__.py`, documented, and become part of the R5.2
  class-name contract (TS ports the same three names). This satisfies R5.5's "owning
  domain error carrying the code" with ONE owning class per builtin, rather than
  per-capability classes — per-capability ownership is expressed by the CODE family
  (`CF*`→filters, `BB*`→bookmarks, `ES*`→engage, …), which is the actual cross-language
  contract (R5.3). Rationale: 145 sites across 6 modules with per-capability classes
  would add ~10 new names to the hierarchy for zero contract gain.

### Backward-compatibility analysis under the chosen policy

- **The 227 `pytest.raises(ValueError)` / 208 message-matched tests all keep passing
  unmodified**: `isinstance(ParamValidationError(...), ValueError)` is True and message
  text is unchanged. Same for the 7 `pytest.raises(TypeError)` tests via `ParamTypeError`.
- **The 124 `pytest.raises(pydantic.ValidationError)` tests keep passing**: P3 leaves
  pydantic-internal raises untouched, and the `VALIDATION_ERROR`/`RESPONSE_VALIDATION_ERROR`
  wrapping happens only at entry-point seams — direct model construction in tests never
  crosses those seams. **Exactly 3 existing tests must be updated** (the §1.7 worklist
  trio): their `pytest.raises(pydantic.ValidationError)` becomes
  `pytest.raises(ResponseValidationError)` + `.code` assertion (pydantic's
  `ValidationError` subclasses `ValueError`, but `ResponseValidationError` deliberately
  does not impersonate it — the wrap is a real, sanctioned behavior change recorded by
  E2, and these 3 tests are on the E2 worklist precisely because they lock the old
  behavior).
- **In-src `except ValueError` handlers keep identical behavior** (audited all 20 hits):
  the only two on converted call paths are workspace.py:9170 (U_FILTER wrap) and
  user_validators.py:467 (U24 wrap); both continue to catch, since the new class IS a
  ValueError. The other 18 guard stdlib parses (`fromisoformat`, `int()`, json) that we
  do not touch.
- **`except TypeError` paths**: none in src wrap the 3 converted TypeError sites
  (fresh grep; user_validators.py:467 includes TypeError and keeps working by subclassing).
- **Catch-broadening is the one observable semantic change**: `except
  MixpanelHeadlessError` now also catches these guard failures. This is the *purpose*
  of the pass (E2) and affects no existing test (fresh grep: no test wraps a converted
  guard in `except MixpanelHeadlessError` expecting fall-through).
- **CLI**: `cli/utils.py` handlers catch `ValueError`/`MixpanelHeadlessError` at
  different levels; subclassing means the more specific existing `ValueError` branches
  keep winning where ordered first. B3 includes a smoke check (`uv run mp --help` +
  the existing CLI test suite) but no CLI code changes.

Docstring policy: every converted site's owning function updates its `Raises:` section
(`ValueError` → `ParamValidationError` with code named), keeping the repo docstring
standard (and R5.3 label comments) intact.

---

## 3. TEST PLAN (GATE-VERDICT R1: ≥2 recordable tests per site)

Strict TDD ordering per batch: write the new failing tests first (they assert class +
`.code` — the code string is the contract; **never** `match=` on message text, R5.4),
then convert the sites, then `just check`.

Per newly-coded site, **≥2 new tests**:

1. **Code+class test** — invoke the guard with a violating input, assert
   `pytest.raises(ParamValidationError)` (or `ParamTypeError` /
   `ResponseValidationError`) and `excinfo.value.code == "<CODE>"`. Where several sites
   share one code (`FD1`, `CD3`, `CD9`, `WS1`, `WR4`, `CD8`), each *site* still gets its
   own test (distinct violating input per raise statement) — that is what makes every
   site's mutation-visible behavior recorded as its own vector.
2. **Seam test (vector-yielding)** — trigger the same guard **through a registered
   recorder entry point** (§5 table: the 5 `Workspace.build_*` facades,
   `bookmark_builders.build_filter_entry`/`build_filter_section`/
   `build_frequency_filter_entry`/`build_date_range`/`build_time_section`,
   `segfilter.build_segfilter_entry`, `user_builders.filter_to_selector`/
   `filters_to_selector`/`extract_cohort_filter`, `types._sanitize_raw_cohort`,
   `types.CohortDefinition.to_dict`) with encodable inputs, asserting the same
   class+code. For constructor guards that fire before any seam call is possible
   (most of §1.3/§1.4), the second test is a direct-construction variant (different
   violating field/branch) and vector yield comes from the §5 registry extension.

Placement and conventions:

- Follow the existing file per module: `tests/unit/test_query_types.py` (types.py
  builder guards), `tests/unit/test_cohort_definition.py` +
  `tests/test_types_cohort_behaviors.py` (cohort families),
  `tests/unit/test_bookmark_builders.py`, `tests/unit/test_segfilter.py`,
  `tests/test_user_builders.py`, `tests/unit/test_workspace.py` /
  `test_workspace_replays.py` (workspace guards), `tests/unit/test_api_client.py` /
  `test_app_api_client.py` (client guards + list_workspaces),
  `tests/unit/test_workspace_crud_edge.py` (response seams), `tests/unit/test_types_replay_*.py`
  (replay models). New test classes named `TestCoded<Family>Codes` inside those files;
  copy each file's existing fixture/mocking patterns exactly (repo TDD rule).
- **Existing tests: updated only where listed.** The 3 §1.7 tests are rewritten
  (pydantic → `ResponseValidationError` + code). Every other existing
  `pytest.raises(ValueError/TypeError)` test **stays untouched** and must stay green —
  that is the policy's regression proof. Where an existing test already covers a site
  with `match=`, the new code-asserting test *supplements* it (R5.4: we add code-based
  assertions; we do not convert message-matched tests wholesale in this pass).
- Registry additions (`exceptions.py` new classes) get their own unit tests in
  `tests/unit/test_exceptions.py` (existing file pattern): inheritance
  (`issubclass(…, ValueError)`), `.code` default (`VALIDATION_ERROR` for
  `ParamValidationError()` without explicit code — keeping the generic code as the
  class default wires R5.5's construction-path fallback), `to_dict()` round-trip.
- Code-uniqueness guard test: one new test asserting no newly-minted full code collides
  with the 175 existing registry codes (source of truth: a small
  `CODED_GUARD_REGISTRY` constant, see B1 deliverables).
- PBT: existing `_pbt` suites (`test_types_pbt.py`, `test_cohort_*_pbt.py`) already
  raise across these guards; they keep passing by subclassing. No new PBT files are
  required by this pass; if a batch touches a property invariant (e.g. `FD1` shared
  across three factories), a small Hypothesis test asserting "all violating quantities
  raise with code FD1" is encouraged but optional (dev profile locally).

Volume estimate: 138 coded sites × 2 ≈ **276 new tests** (+6 seam-family tests for
§1.7 sweep, +hierarchy/uniqueness tests). Coverage stays ≥90 trivially (new lines are
raise-site edits + new classes, all directly tested).

---

## 4. BATCHES

Each batch is one TDD workflow task: tests first → convert → docstrings → `just check`
green → one commit (plus a follow-up commit if registry/plugin changes land with it).
Line numbers re-verified at HEAD before each batch starts.

### B1 — `types.py` (cohort/metric families + all dataclass/builder guards)

- Files: `src/mixpanel_headless/exceptions.py` (add the three classes + docstrings),
  `src/mixpanel_headless/__init__.py` (exports), `src/mixpanel_headless/types.py`
  (98 sites: §1.1–§1.4), new constant module or dict `CODED_GUARD_REGISTRY` (single
  source listing every full code minted by this pass; lives in `exceptions.py` or
  `types.py` — implementer's call, must be importable by tests and the recorder).
- Tests: `tests/unit/test_exceptions.py`, `tests/unit/test_query_types.py`,
  `tests/unit/test_cohort_definition.py`, `tests/test_types_cohort_behaviors.py`,
  `tests/test_types_flow.py`, `tests/unit/test_types_replay_*.py`.
- Twin verifications owed: `V13_METRIC_MATH_PROPERTY`, `V26_PERCENTILE_REQUIRES_VALUE`,
  `V8_DATE_FORMAT`/`V8_DATE_INVALID`, `V12_BUCKET_SIZE_POSITIVE`, `V18_BUCKET_ORDER`,
  `FL3_FORWARD_RANGE`/FL-reverse, `CM5_INLINE_COHORT_METRIC` (confirmed).
- Expected vector yield on re-extraction: ~40–80 immediately via existing seams
  (facade `build_*` tests + `CohortDefinition.to_dict` + `_sanitize_raw_cohort` paths,
  incl. the 1 worklist test), **~150–200 total once the §5 guard-entry registry
  extension lands** (constructor families TC/FB/FF/LC/FD/GB/CD/CF/CB/CM).

### B2 — `bookmark_builders.py` + `segfilter.py` (+ expressions/transforms no-ops)

- Files: `src/mixpanel_headless/_internal/bookmark_builders.py` (8 sites, §1.5),
  `src/mixpanel_headless/_internal/segfilter.py` (4 sites). `expressions.py` /
  `transforms.py`: zero sites — batch records that in its ledger note and touches
  neither.
- Tests: `tests/unit/test_bookmark_builders.py`, `tests/unit/test_segfilter.py`,
  `tests/test_build_cohort_params.py`.
- Conformance-side (same batch, separate commit): add registry builder entries for
  `bookmark_builders.build_group_section`, `build_flow_property_filter`,
  `build_flow_cohort_filter` (currently unregistered — their guards are otherwise
  invisible to the recorder; `build_filter_entry`/`build_filter_section`/
  `build_frequency_filter_entry`/`build_segfilter_entry` are already registered).
- Expected vector yield: **~25–45** (5 worklist tests recovered + new seam tests across
  12 sites; all 12 sites sit behind registered-or-newly-registered module functions).

### B3 — `user_builders.py` + `workspace.py` + `api_client.py` guards + generic codes

- Files: `src/mixpanel_headless/_internal/query/user_builders.py` (13 sites),
  `src/mixpanel_headless/workspace.py` (9 sites + response-seam helper),
  `src/mixpanel_headless/_internal/api_client.py` (6 sites + `list_workspaces` seam).
  Generic-code wiring: `ResponseValidationError` applied per §1.7;
  `ParamValidationError`'s class-level default code IS `VALIDATION_ERROR` (B1), so the
  construction-path generic needs no additional plumbing beyond documentation.
- Tests: `tests/test_user_builders.py`, `tests/test_query_user_edge_cases.py`,
  `tests/unit/test_workspace.py`, `tests/unit/test_workspace_replays.py`,
  `tests/unit/test_api_client.py`, `tests/unit/test_app_api_client.py`,
  `tests/unit/test_workspace_crud_edge.py` (3 updated tests + new code assertions).
- Expected vector yield: **~35–60** — 8 worklist tests recovered (user_builders ×6 via
  the registered `filter_to_selector`/`filters_to_selector` seams; +2 response-path
  wire vectors gaining `expect.error`), new seam tests across ES1–ES13, plus
  `wire`-kind error vectors for workspace/api_client guards whose tests run against
  mock transports (guards that raise pre-transport land in `wire_call_no_transport`
  unless the test uses a builder seam — the workspace/api_client guard yield is
  therefore the most uncertain; the floor is the 8 recovered worklist tests).

Batch ordering is B1 → B2 → B3 (B1 lands the exception classes everything else
imports). After B3: full re-extraction + drift check + D9 smoke + EXTRACTION-LEDGER
refresh + TS corpus re-sync (GATE-VERDICT R1/R4; separate addendum tasks, with R2/R3
handled during that re-extraction per their own recommendations — not this design).

Combined coding-pass yield estimate: **~210–305 extracted vectors** (arbiter's
plausible band was 260–390 for ~130 sites; the honest floor here is 14 recovered
worklist tests, and the estimate is contingent on the §5 registry extension for
constructor families). With E1's ~81 storybook parse vectors: 2,609 + ~291–386 →
**~2,900–2,995**, i.e. the 3,000 target is reachable but not guaranteed; per R1 any
residual shortfall is documented in EXTRACTION-LEDGER.md, not gated.

---

## 5. VECTOR IMPACT (recorder mechanics, verified against `conformance/record/` at 852d718)

**How coded raises get picked up automatically — no plugin change needed for the
14-test worklist:**

- `emit.py::_encode_error` (line ~732) returns a structured error for ANY
  `MixpanelHeadlessError` instance: `{"class": type(error).__name__, "code": error.code,
  "details_contain": …}`; it returns `None` (→ `uncoded_raise` exclusion) only for
  non-hierarchy exceptions. `ParamValidationError`/`ParamTypeError`/
  `ResponseValidationError` are `MixpanelHeadlessError` subclasses → encoded, with
  class name + code exactly as R5.2/R5.3 want.
- Builder path: `emit.py::_builder_vector` (~834) emits `kind: "builder"` with
  `expect.error` for coded single-guard raises (`kind: "validation-error"` is reserved
  for `BookmarkValidationError` carrying an `errors` list — the new guard vectors are
  builder-kind error vectors; the manifest `by_kind` split will shift accordingly, which
  is fine: `vector.schema.json` allows `expect.error` on builder vectors).
- Wire path: `emit.py::_wire_vector` (~1031) stops returning `(None, "uncoded_raise")`
  for these raises; wire tests whose measured call raised AFTER transport fired emit
  wire vectors with `expect.error` (the two CRUD empty-response worklist tests +
  `list_workspaces`).
- Re-run of extraction therefore converts the 14 worklist exclusions into vectors
  purely by virtue of the src change. `exclusions.uncoded_raise` drops toward 0
  (residual: any test hitting the P3 pydantic-internal sites or the excluded
  api_client:411 guard through a seam — expected ≈0).

**Two recorder-side changes ARE needed for full yield (conformance/, not src/):**

1. **Registry entries for the three unregistered bookmark_builders functions** (B2,
   listed there). Mechanical: same `RegistryEntry(kind=KIND_BUILDER, capability=…)`
   pattern; `registry.py::resolve_owner` already handles module-level functions.
2. **Guard entries for constructor-guard families (B1's big yield).** Most §1.3/§1.4
   sites fire inside `__post_init__`/classmethods during test-side construction —
   outside every registered seam, so their new tests emit no vectors today.
   Extension: register the guard-bearing constructors/classmethods as builder entries
   (`target="mixpanel_headless.types:Metric.__init__"` style resolves via the existing
   `Class.method` branch of `resolve_owner`; classmethods like `Filter.in_the_last`,
   `CohortCriteria.performed`, `CohortDefinition.all` register directly), with a new
   `RegistryEntry` flag (e.g. `error_only=True`) honored in `_builder_vector` so
   **success-path constructions emit nothing** (avoids flooding the corpus with
   trivial construction-output vectors and keeps re-extraction review tractable);
   the `state.depth > 0` re-entrancy guard in `plugin.py::_build_wrapper` (~686)
   already suppresses nested constructions inside facades, so no attribution changes
   are needed. Input encodability is already in place — the codec table encodes these
   dataclasses as facade inputs today. This is a plugin change under the rig's own
   standards (mypy --strict on conformance/, tooling tests) and lands with B1's
   conformance commit; the TS runner needs the mirrored entry-point mapping only when
   Phase 3 ports these families (unported vectors are counted, not failed).
- Schema: **no `vector.schema.json` change needed** — `expect.error` with
  `class`/`code`/`details_contain` is already the operative shape; new codes are data,
  not schema. (R3's `message_not_contains` field is a separate addendum decision, out
  of scope here.)
- Determinism: re-extraction after the coding pass is expected to differ ONLY by
  (a) former `uncoded_raise` tests now emitting vectors, (b) new tests' vectors,
  (c) manifest counts/exclusion lists; a before/after manifest diff is part of the
  re-extraction task's ledger note.

---

## 6. Done criteria for the coding pass (per batch and overall)

1. Every §1 site raises its assigned coded exception with byte-identical message;
   `git grep "raise ValueError\|raise TypeError"` over the six modules returns only
   the documented exclusions (6 × P3 pydantic-internal, api_client.py:411).
2. All existing tests pass unmodified except the 3 enumerated §1.7 updates.
3. ≥2 new code-asserting tests per site; no new test asserts message text.
4. `just check` green (lint, fmt, mypy --strict, coverage ≥90, build) before each
   commit; commits stay local on `ts-port/phase1-addendum`.
5. `CLAUDE.md`, `.claude/`, `pyproject.toml` untouched; conformance/ changes limited
   to §5's registry/emit additions + their tooling tests.
