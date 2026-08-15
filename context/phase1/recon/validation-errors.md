# Recon: Validation-Error Raising & Assertion Map

Commit `5269674` (branch `fix/latent-bugs-stress-test`). Companion machine-readable data: `validation-errors.json` (same directory). Purpose: ground rulebook R5.3/R5.4/R5.5 — validation-error corpus vectors must extract **codes**, not messages.

## 1. Exception classes (src/mixpanel_headless/exceptions.py)

| Class | Location | Code attribute | Notes |
|---|---|---|---|
| `MixpanelHeadlessError` | exceptions.py:26-89 | `.code` property (exceptions.py:53-56), default `"UNKNOWN_ERROR"`; also `.message`, `.details`, `.to_dict()` | Base for all library errors |
| `ValidationError` (frozen dataclass, NOT an exception) | exceptions.py:1155-1232 | field `code: str = "VALIDATION_ERROR"` (exceptions.py:1191) | The rule-code carrier. Fields: `path`, `message`, `code`, `severity` (`"error"`/`"warning"`), `suggestion: tuple[str,...]|None`, `fix: dict|None`. `to_dict()` at 1203; `__str__` at 1222 embeds `"Did you mean '<suggestion[0]>'?"` (1231) |
| `BookmarkValidationError` | exceptions.py:1235-1303 | exception `.code == "BOOKMARK_VALIDATION_ERROR"` (1288); rule codes live on `.errors: tuple[ValidationError, ...]` (1291) | The exception actually raised for ALL query/bookmark/user-query validation failures. Also `.error_count`, `.warning_count`. Its message string is a concatenation of per-error `__str__` — message text duplicates the structured data |
| `BusinessContextValidationError` | exceptions.py:1112-1149 | fixed `code="BUSINESS_CONTEXT_TOO_LONG"` (1147) | single rule, details carry `length`/`max` |
| `DateRangeTooLargeError` | exceptions.py:836-903 | fixed `code="DATE_RANGE_TOO_LARGE"` (883) | typed attrs `days_requested`, `max_days` |
| `InvalidArgumentError` | exceptions.py:355-428 | `code="INVALID_ARGUMENT"` + `.violation` Literal discriminator (417-422) | login flag-combination misuse |

**Answer to "is there a .code/.rule/.field attribute":** yes — every exception has `.code` (machine-readable); the per-rule code lives on `ValidationError.code`; there is no `.rule` attribute; `.field` is served by `ValidationError.path` (JSONPath-like). This is exactly the contract R5.3/R5.4 want vectors to capture: `{path, code, severity}` per error, with `message`, `suggestion`, `fix` advisory.

`BookmarkValidationError` raise sites: 23, all in `src/mixpanel_headless/workspace.py` (lines 2597, 2612, 2633, 2653, 2693, 2719, 3014, 3041, 3776, 3805, 3829, 4176, 4202, 5247, 5343, 9118, 9155, 9171, 9196, 9210, 9223, 9243, 9320). The validators themselves NEVER raise — they return `list[ValidationError]`; the workspace facade decides to raise (validation.py:11-12 docstring).

## 2. Where the rule codes live

**No registry, no constants module.** Every code is an inline string literal passed as `ValidationError(code="...")`. Messages are f-strings built adjacent to each code.

| Family | File | Mechanism |
|---|---|---|
| V0-V27 (incl. V3B, V22 control/invisible), F*, FL*, FLB*, R1-R13, B1-B26, CP1-CP6, DG1, CB3, CM5 | `src/mixpanel_headless/_internal/validation.py` (3,090 lines) | 167 distinct code literals across `validate_query_args` (:1885), `validate_bookmark` (:2288), `validate_funnel_args` (:779), `validate_retention_args` (:1179), `validate_flow_args` (:1498), `validate_flow_bookmark` (:1772), `_validate_custom_property` (:96) |
| U0-U30 (bare codes, e.g. `code="U1"`), UP1-UP4 | `src/mixpanel_headless/_internal/query/user_validators.py` (580 lines) | `validate_user_args` (U-rules, :132-472) and `validate_user_params` (UP-rules, :516-576). NOTE: U codes have **no descriptive suffix** — just `"U1"`..`"U30"` |
| S1-S9 + B0_INVALID_LITERAL | `src/mixpanel_headless/_internal/bookmark_schema.py` | pydantic→ValidationError adapter `validate_with_pydantic` (:170) with static map `extra_forbidden → S3_UNKNOWN_FIELD` (:75) and path-aware `_sorting_code_mapper` (:99-166). Pydantic errors here never escape as `pydantic.ValidationError` — they are translated to coded `ValidationError`s |

Family-label discrepancies (labels in mission vs. actual code strings):
- **V22a/V22b** are comments only (validation.py:1996, 2009); real codes: `V22_CONTROL_CHAR_EVENT`, `V22_INVISIBLE_EVENT`.
- **B22b** is a comment (validation.py:2523); real codes: `B22_COHORT_BEHAVIOR_ID`, `B22_COHORT_MISSING_IDENTIFIER`.
- **CF1-CF2, CB1-CB2, CM1-CM2** are docstring labels only; enforced as **plain `ValueError`** in `types.py` `_validate_cohort_args` (types.py:8991-8994), called from `Filter._build_cohort_filter` (types.py:7724), `CohortBreakdown.__post_init__` (types.py:9228), `CohortMetric.__post_init__` (types.py:9281). **Uncoded** → R5.5 exclusion until coded.
- **CB3** IS coded: `CB3_RETENTION_MIXED_BREAKDOWN` (validation.py:1452).
- **CM5** is dual-enforced: `ValueError` at construction (types.py:9282) AND `CM5_INLINE_COHORT_METRIC` (validation.py:1978) for the bypass path.
- **U9** is a runtime type guard, not a code (user_validators.py:233).
- **V25 does not exist** (numbering gap V24→V26).

Total distinct code strings in source: **175** (167 in validation.py+user_validators.py, +10 from bookmark_schema.py, −2 overlap: S4/S5 emitted in both).

## 3. Assertion styles in tests (headline risk quantified)

Grep-derived counts across `tests/` (238 files, ~7,000 tests):

| Style | Count | Example |
|---|---|---|
| `pytest.raises(...)` total | 1,079 | — |
| `pytest.raises(..., match="message text")` (same-line) | 368 (442 total `match=` incl. wrapped lines) | tests/unit/test_query_validation.py:350 `pytest.raises(BookmarkValidationError, match="formula requires at least 2 events")` |
| `.code == "<CODE>"` equality | 346 (423 total `e.code`/`exc.value.code` refs) | tests/test_validation_funnel.py:84 `assert any(e.code == "F1_MIN_STEPS" for e in errors)` |
| prefix-in-code (`"B16" in e.code`, `e.code.startswith("B17")`) | ~7 sites | tests/test_validation_bypass.py:130,238-250; tests/unit/test_validation.py:626; tests/unit/test_query_pbt.py:778 |
| `exc.value.code == "..."` (exception-level code) | 34 | tests/unit/test_pagination.py:644 |
| `pytest.raises(BookmarkValidationError)` | 127 total; 70 with same-line `match=` | facade-level tests |
| `pytest.raises(ValueError)` | 227 total; 208 with `match=` | tests/test_validation_funnel.py:140 `match="FunnelStep.event must be a non-empty string"` |
| `pytest.raises(TypeError)` | 7 | — |
| `pytest.raises(pydantic ValidationError)` | 124 | CRUD-params model tests (tests/unit/test_types_crud.py etc.) |

**The split is bimodal and layer-correlated:**
- Tests that call `validate_*()` **directly** (tests/test_validation_funnel.py, test_validation_retention.py, test_validation_flow.py, test_validation_cohort.py, test_user_validators.py, tests/unit/test_validation.py) assert on `ValidationError.code` → **extraction-safe**.
- Tests that go through the **Workspace facade** (`ws.query(...)` etc.) overwhelmingly use `pytest.raises(BookmarkValidationError, match="<message fragment>")` → **message-coupled**. 70+ such sites.
- ALL tests of the uncoded `ValueError` construction guards (CF/CB/CM families, FunnelStep/Exclusion guards) match on message text (208 sites) — unavoidable since there is no code.

**Headline risk:** ~35-40% of validation-failure assertions in the suite are message-text matches. Per R5.4 the corpus must NOT inherit this: for any coded path, extract `(path, code, severity)` from `ValidationError`; treat `message`/`suggestion`/`fix` as advisory. The record-mode plugin should capture `BookmarkValidationError.details["errors"]` (already `to_dict()`-serialized, exceptions.py:1283-1287) rather than `str(exc)`.

## 4. Code → test inventory

Full 175-code map in `validation-errors.json` (`codes` key: `{tests: [...], count, coverage}`). Summary:

- **155/175** codes have ≥1 test containing the exact quoted code string.
- **4** covered only by prefix-style assertions: `B16_INVALID_RESOURCE_TYPE`, `B17_INVALID_PROPERTY_TYPE`, `B18B_INVALID_CP_ID` (tests/test_validation_bypass.py), `V19_FORMULA_BOUNDS` (tests/unit/test_query_pbt.py:778,803,852).
- **7** covered only by message-text matches (code string never appears in tests): `V14_METRIC_REJECTS_PROPERTY` (test_query_validation.py:302 `match="property is only valid"`), `V26_PERCENTILE_REQUIRES_VALUE`, `V27_HISTOGRAM_REQUIRES_PER_USER`, `CM5_INLINE_COHORT_METRIC`, `CP4_INVALID_INPUT_KEY`, `CP5_FORMULA_TOO_LONG`, `CP6_EMPTY_INPUT_NAME`.
- **9 codes with NO test found** (neither code string, prefix, nor message fragment):
  - `B8_MISSING_EVENT_NAME` (validation.py:2506)
  - `B11_INVALID_PER_USER` (validation.py:2654)
  - `B13_INVALID_DATE_RANGE_TYPE` (validation.py:2778, severity=warning)
  - `B19_INVALID_FILTERS_DETERMINER` (validation.py:2556, severity=warning)
  - `B20B_FILTER_VALUE_NOT_FINITE` (validation.py:2936, 2946)
  - `V16_FORMULA_SYNTAX` (validation.py:2122)
  - `V21_INVALID_EVENT_TYPE` (validation.py:1961)
  - `V23_ROLLING_TOO_LARGE` (validation.py:2172)
  - `U25` (user_validators.py:256)
  - (Caveat: `V16`/`V21`/`V23` strings appearing in tests/live/test_040_query_completeness_live.py are a DIFFERENT numbering scheme from that spec's test plan, not these codes.)

Highest-coverage codes (test-reference counts): `V7_LAST_POSITIVE` (21), `DG1_INVALID_DATA_GROUP_ID` (18), `V8_DATE_FORMAT` (18), `F1_MIN_STEPS` (14), `F3_CONVERSION_WINDOW_POSITIVE` (14), `B9_INVALID_MATH` (12), `V12B_BUCKET_REQUIRES_NUMBER` (12), `V24_BUCKET_NOT_FINITE` (12), `U3` (12).

## 5. difflib suggestion sites (advisory per R5.3 — exclude from vectors)

Single `get_close_matches` import/call:
- `validation.py:19` (import), `validation.py:427` in `_suggest(value, valid, n=3, cutoff=0.5)`.
- Consumers: `_enum_error` (validation.py:452; used at **26** call sites in validation.py), `validate_funnel_args` F12 reentry-mode (validation.py:1142), `validate_retention_args` R13 unbounded-mode (validation.py:1464).
- Downstream message coupling: `ValidationError.__str__` appends `"Did you mean '<first>'?"` (exceptions.py:1231) which flows into the `BookmarkValidationError` summary message (exceptions.py:1272-1281). 85 test lines reference `suggestion`.
- `EventNotFoundError` also emits "Did you mean" (exceptions.py:707) but from discovery-side `similar_events`, not difflib.
- `user_validators.py` uses no suggestions at all.

Porting note: TS has no difflib; `_suggest` output ordering depends on `difflib.SequenceMatcher` ratios — vectors must therefore omit `suggestion` (and the message tail it produces).

## 6. Builtin ValueError/TypeError + pydantic sites in pure builders (R5.5 — excluded until coded)

`raise ValueError|TypeError` counts per pure/builder file (full per-file table in JSON `uncoded_sites`):
- `src/mixpanel_headless/types.py`: **104** sites — construction guards (`_validate_cohort_args` :8991-8994 = CF1/CF2/CB1/CB2/CM1/CM2; `CohortMetric.__post_init__` :9282 = CM5; `Filter._validate_date`; `Metric` property-math guard = V13 fail-fast; FunnelStep/Exclusion/RetentionEvent/FlowStep/InlineCustomProperty guards).
- `src/mixpanel_headless/_internal/query/user_builders.py`: **13** sites (e.g. `_prop_ref` :54 non-string property; :219 unsupported filter operator).
- `src/mixpanel_headless/_internal/bookmark_builders.py`: **8** sites (:395, :609, :621, :673, :680, :689, :696, :703).
- `src/mixpanel_headless/_internal/segfilter.py`: **4** sites (:143, :172, :227, :299).
- `src/mixpanel_headless/workspace.py`: **9** sites (facade arg guards, mixed purity).

pydantic.ValidationError: escapes uncaught only from Pydantic **model construction** in `types.py` (CRUD params — `CreateCohortParams`, webhook/alert/experiment params etc.; docstrings at accounts.py:182, types.py:12157 document propagation). The bookmark-sorting pydantic path is fully translated to `S*`/`B0` codes and never escapes (bookmark_schema.py:215-221).

Test exposure (estimates, by grep): `pytest.raises(ValueError` = 227 total across tests, of which ~**38** are in pure-builder/validator test files (test_types_*, test_build_*, test_validation_*, test_user_builders, test_cohort_*_pbt); `pytest.raises(TypeError` = 7; pydantic `raises(ValidationError` = 124 (CRUD model tests). All of these assert message text or pydantic error `type` (tests/unit/test_bookmark_schema.py:64,105) — none have library codes; per R5.5 these paths stay OUT of the conformance corpus until a coding pass lands (candidate codes already named in docstrings: CF1, CF2, CB1, CB2, CM1, CM2).

## Extraction directives distilled

1. Vector shape for coded failures: `{errors: [{path, code, severity}]}` sourced from `BookmarkValidationError.errors` / validator return lists. Never `message`, `suggestion`, `fix` (R5.3, R5.4).
2. U/UP codes are bare (`"U1"`); do not "normalize" them to descriptive names.
3. 9 codes have zero tests — corpus record-mode will produce no vectors for them from the existing suite; they need hand-written seed vectors or they silently drop out of conformance.
4. Uncoded `ValueError` guards (CF/CB/CM + 129 other builder sites) are excluded per R5.5; track as a follow-up coding task, since 208 message-matched ValueError tests show these paths ARE behaviorally load-bearing.
