# Builder Registry — Pure (no-I/O) Builder / Validator / Transform Entry Points

Phase-1 recon for the conformance-corpus record-mode plugin ("builder vectors",
plan §5 / L282–302: ~1,800 pure builder tests). Every claim below is cited as
`file:line` against branch `fix/latent-bugs-stress-test` @ `5269674`.

Machine-readable companion: `builder-registry.json` (same directory).

## Method

- Function inventory: `grep -n "^def \|^class "` per module + `ast.unparse` of
  every top-level `FunctionDef` (exact signatures below are ast-derived, not
  hand-copied).
- Test counts: `uv run python -m pytest --collect-only -q <file>` per file
  (collected node counts, i.e. **post-parametrize**; PBT files count Hypothesis
  test *functions*, each of which runs 100/200 examples). One-shot collection of
  all 38 builder-related files: **1,723 collected** (per-file loop sums to
  1,713; the ±10 delta is package-level conftest interplay — both figures are
  cited runs, not estimates). This corroborates the plan's ~1,800 figure
  (typescript-port-plan.md:301-302).
- Purity: import audit per module (no `httpx`, no `os`/`pathlib`, no env
  reads). All functions are synchronous. Exceptions (clock/UUID) are flagged
  per entry under *hazards*.

## 1. Two-level structure: Workspace facade → module functions

The five public `Workspace.build_*` methods are thin façades. Each delegates to
a private `Workspace._resolve_and_build_*` orchestrator which composes **pure
module-level validators and builders** — no `self._http`, no session state, no
network anywhere on these paths (verified by reading each body; the only `self`
usage is calling sibling private builders):

| Public method | Orchestrator | Layer-1 validator | Param assembler | Layer-2 validator |
|---|---|---|---|---|
| `Workspace.build_params` (workspace.py:2412) | `_resolve_and_build_params` (workspace.py:2527) | `validate_query_args` (validation.py:1885) + `_scan_custom_properties` (validation.py:218, called at workspace.py:2691) | `Workspace._build_query_params` (workspace.py:2028) → bookmark_builders.* | `validate_bookmark` (validation.py:2288, called at workspace.py:2717) |
| `Workspace.build_funnel_params` (workspace.py:3183) | `_resolve_and_build_funnel_params` (workspace.py:2911) | `validate_funnel_args` (validation.py:779) + `_scan_custom_properties` (workspace.py:3012) | `Workspace._build_funnel_params` (workspace.py:2727) → bookmark_builders.* | `validate_bookmark(bookmark_type="funnels")` (workspace.py:~3040) |
| `Workspace.build_flow_params` (workspace.py:3969) | `_resolve_and_build_flow_params` (workspace.py:3616) | `validate_flow_args` (validation.py:1498) + `_scan_custom_properties` (workspace.py:3803) | `Workspace._build_flow_params` (workspace.py:3474) → `build_segfilter_entry`, `build_date_range`, `build_flow_cohort_filter`, `build_flow_property_filter`, `build_group_section` | `validate_flow_bookmark` (validation.py:1772, called at workspace.py:~3828) |
| `Workspace.build_retention_params` (workspace.py:4330) | `_resolve_and_build_retention_params` (workspace.py:4081) | `validate_retention_args` (validation.py:1179) + `_scan_custom_properties` (workspace.py:~4170) | `Workspace._build_retention_params` (workspace.py:3302) → `build_filter_entry`, `build_time_section`, `build_filter_section`, `build_group_section`, `build_time_comparison` | `validate_bookmark(bookmark_type="retention")` (workspace.py:~4201) |
| `Workspace.build_user_params` (workspace.py:9578) | `_resolve_and_build_user_params` (workspace.py:9031) | `validate_user_args` (user_validators.py:58, called at workspace.py:~9132) | inline dict assembly + `extract_cohort_filter` (workspace.py:9166), `filters_to_selector` (workspace.py:9170), `_sanitize_raw_cohort` (workspace.py:9189), `json.dumps` for `filter_by_cohort` | `validate_user_params` (user_validators.py:479, called at workspace.py:~9318) |

**Design implication (both levels matter):** the workspace level is the public
input→output contract (kwargs in, plain `dict` out — this is what the plan's
"public builder entry points" registry records, plan:301-302); the module level
is where the shared building blocks live, and the same module function is
reached from multiple workspace paths (e.g. `build_filter_entry` serves
insights, funnel, and retention). `tests/unit/test_delegation_equivalence_pbt.py`
(6 PBT functions) already locks facade≡module equivalence on the Python side.
Recommendation: **record vectors at the Workspace `build_*` level** (captures
the full compose), and keep module-level vectors only for the three Filter
translation paths + `build_date_range`/`build_time_section` (the date-hazard
functions), since those need pinned-clock treatment.

## 2. The three Filter translation paths (shared `types.Filter` → three encodings)

| # | Target encoding | Entry point | Consumed by |
|---|---|---|---|
| 1 | Bookmark JSON filter clause (`{"resourceType", "propertyName", "filterOperator", ...}`) | `mixpanel_headless._internal.bookmark_builders.build_filter_entry(f: Filter) -> dict` (bookmark_builders.py:466), plus wrapper `build_filter_section` (:172) and frequency variant `build_frequency_filter_entry` (:784) | insights `_build_query_params` (workspace.py:2028), funnel `_build_funnel_params` (workspace.py:2727 → `build_filter_entry` at ~:2801), retention `_build_retention_params` (workspace.py:3302 → :3373) |
| 2 | Flows segfilter dict (`{"filter": {"operator", "operand"}, "selected_property_type", ...}`) | `mixpanel_headless._internal.segfilter.build_segfilter_entry(f: Filter) -> dict` (segfilter.py:252); typed dispatch via `_build_string_filter` (:129), `_build_number_filter` (:158), `_build_boolean_filter` (:189), `_build_datetime_filter` (:203), `_convert_date_format` (:105, `YYYY-MM-DD` → `MM/DD/YYYY`) | `Workspace._build_flow_params` per-step filters (workspace.py:3474, call at ~:3563) |
| 3 | Engage selector string (`'properties["plan"] == "premium"'`) | `mixpanel_headless._internal.query.user_builders.filter_to_selector(f: Filter) -> str` (user_builders.py:82), `filters_to_selector(filters: list[Filter]) -> str` (:222), with `_format_value` (:26, string escaping — the plan's highest-priority fuzz target, plan:496), `_prop_ref` (:44), `_is_cohort_filter` (:63); cohort split-out via `extract_cohort_filter` (:251) | `Workspace._resolve_and_build_user_params` (workspace.py:9170) |

## 3. Registry — entry points

Output type legend: all builders emit **plain dicts / lists / strs** (JSON-safe
unless noted); all validators emit **`list[ValidationError]`**
(exceptions.py dataclass with `path`/`message`/`code`/`severity` — vector
serialization = list of its dicts). Purity: **pure/sync** unless a hazard says
otherwise; none touch network/fs/env.

### 3.1 Workspace facade (public; record level A)

| API | Signature (condensed) | Output | Covering tests (collected counts) | Hazards |
|---|---|---|---|---|
| `Workspace.build_params` (workspace.py:2412) | `(events: str\|Metric\|CohortMetric\|Formula\|Sequence[...], *, from_date=None, to_date=None, last=30, unit="day", math="total", math_property=None, per_user=None, percentile_value=None, group_by=None, where=None, formula=None, formula_label=None, rolling=None, cumulative=False, mode="timeseries", time_comparison=None, data_group_id=None) -> dict[str, Any]` | plain dict (`sections` + `displayOptions`) | tests/unit/test_query_params.py (86), test_query_pbt.py (28), test_query_validation.py (76), test_query_validation_pbt.py (4), test_query_integration.py (22), tests/test_build_cohort_params.py (67), test_custom_property_builders.py (23), test_custom_property_types.py (47), test_custom_property_query.py (13), test_custom_property_pbt.py (10), test_validation_bypass.py (20), test_validation_bypass_r2.py (16, shared), tests/unit/test_delegation_equivalence_pbt.py + test_roundtrip_soundness_pbt.py (13, shared) | `date.today()` via `build_date_range` when `to_date is None` (bookmark_builders.py:114) — vectors must either pin the clock or always pass explicit `from_date`+`to_date`; raises `BookmarkValidationError` on invalid input (error-vector kind) |
| `Workspace.build_funnel_params` (workspace.py:3183) | `(steps: list[str\|FunnelStep], *, conversion_window=14, conversion_window_unit="day", order="loose", from_date=None, to_date=None, last=30, unit="day", math="conversion_rate_unique", math_property=None, group_by=None, where=None, exclusions=None, holding_constant=None, mode="steps", reentry_mode=None, time_comparison=None, data_group_id=None) -> dict[str, Any]` | plain dict | tests/test_build_funnel_params.py (77), tests/test_validation_funnel.py (129, exercises validator through this facade), tests/test_workspace_funnel.py (partial) | same `date.today()` hazard via `build_time_section`/`build_date_range` |
| `Workspace.build_flow_params` (workspace.py:3969) | `(event: str\|FlowStep\|Sequence[...], *, forward=3, reverse=0, from_date=None, to_date=None, last=30, conversion_window=7, conversion_window_unit="day", count_type="unique", cardinality=3, collapse_repeated=False, hidden_events=None, mode="sankey", where=None, data_group_id=None, segments=None, exclusions=None) -> dict[str, Any]` | plain dict (flows API params, incl. `date_range`, `filter_by_event`, `segments`) | tests/unit/test_workspace_flow.py (49), tests/test_validation_flow.py (116, via facade), test_types_flow_pbt.py (partial), test_validation_bypass_r2.py (shared) | `date.today()` via `build_date_range` (bookmark_builders.py:114) |
| `Workspace.build_retention_params` (workspace.py:4330) | `(born_event: str\|RetentionEvent, return_event: str\|RetentionEvent, *, retention_unit="week", alignment="birth", bucket_sizes=None, from_date=None, to_date=None, last=30, unit="day", math="retention_rate", group_by=None, where=None, mode="curve", unbounded_mode=None, retention_cumulative=False, time_comparison=None, data_group_id=None) -> dict[str, Any]` | plain dict | tests/test_build_retention_params.py (39), tests/test_validation_retention.py (107, via facade), tests/test_workspace_retention.py (partial) | `date.today()` via time section |
| `Workspace.build_user_params` (workspace.py:9578) | `(*, where: Filter\|list[Filter]\|str\|None=None, cohort: int\|CohortDefinition\|None=None, properties=None, sort_by=None, sort_order="descending", search=None, distinct_id=None, distinct_ids=None, group_id=None, as_of: str\|int\|None=None, mode="aggregate", aggregate="count", aggregate_property=None, percentile=None, segment_by=None, limit=1, parallel=False, workers=5, include_all_users=False) -> dict[str, Any]` | plain dict (engage API params; `where` is a selector **string**, `filter_by_cohort` is a **JSON-encoded string** via `json.dumps`, workspace.py:9186-9190) | tests/test_workspace_build_user_params.py (68), test_query_user_edge_cases.py (28, shared), test_user_query_pbt.py (29, shared), test_query_user_structural.py (13, shared) | `date.today()` in `validate_user_args` as_of future-date check (user_validators.py:211,217) — vectors with `as_of` dates near "today" flip over time; nested-JSON-string output needs an encoding rule in the vector schema |

Private pure orchestrators/assemblers on these paths (record level B if
needed): `_resolve_and_build_params` (workspace.py:2527), `_build_query_params`
(:2028), `_build_funnel_params` (:2727), `_resolve_and_build_funnel_params`
(:2911), `_build_retention_params` (:3302), `_build_flow_params` (:3474),
`_resolve_and_build_flow_params` (:3616), `_resolve_and_build_retention_params`
(:4081), `_resolve_and_build_user_params` (:9031).

### 3.2 `mixpanel_headless._internal.bookmark_builders` (module level; exact ast signatures)

Covering tests: tests/unit/test_bookmark_builders.py (**109**),
test_bookmark_builders_pbt.py (**8**); heavily re-exercised through every
facade test above. All output plain dict/list. All pure except the flagged one.

| Function | Signature | Hazards |
|---|---|---|
| `build_time_section` (:71) | `(*, from_date: str\|None, to_date: str\|None, last: int, unit: QueryTimeUnit) -> list[dict[str, Any]]` | delegates date defaulting to `build_date_range` |
| `build_date_range` (:129) | `(*, from_date: str\|None, to_date: str\|None, last: int) -> dict[str, Any]` | **`date.today().isoformat()` at bookmark_builders.py:114** when `to_date is None` |
| `build_filter_section` (:172) | `(where: Filter\|FrequencyFilter\|Sequence[...]\|None) -> list[dict[str, Any]]` | — |
| `patch_custom_property_filters_for_transform` (:207) | `(filter_entries: list[dict]) -> list[dict]` | — |
| `build_group_section` (:241) | `(group_by: str\|GroupBy\|CohortBreakdown\|FrequencyBreakdown\|Sequence[...]\|None, *, data_group_id: int\|None=None) -> list[dict]` | — |
| `build_filter_entry` (:466) | `(f: Filter) -> dict[str, Any]` | translation path #1 |
| `build_flow_property_filter` (:580) | `(filters: list[Filter]) -> dict[str, Any]` | — |
| `build_flow_cohort_filter` (:638) | `(where: Filter\|list[Filter]) -> dict[str, Any]\|None` | — |
| `build_frequency_group_entry` (:719) | `(fb: FrequencyBreakdown, *, data_group_id: int\|None=None) -> dict` | — |
| `build_frequency_filter_entry` (:784) | `(ff: FrequencyFilter) -> dict[str, Any]` | — |
| `build_time_comparison` (:837) | `(tc: TimeComparison) -> dict[str, str]` | — |
| private: `_build_composed_properties` (:31), `_build_cohort_group_entry` (:403, uses `_sanitize_raw_cohort` at :444), `_build_list_contains_entry` (:530) | | — |

### 3.3 `mixpanel_headless._internal.segfilter`

Covering tests: tests/unit/test_segfilter.py (**49**) + flow facade tests.

| Function | Signature | Hazards |
|---|---|---|
| `build_segfilter_entry` (:252) | `(f: Filter) -> dict[str, Any]` | translation path #2; raises `ValueError` on unsupported operators |
| private: `_convert_date_format` (:105) `(date_str: str) -> str`, `_build_string_filter` (:129), `_build_number_filter` (:158), `_build_boolean_filter` (:189), `_build_datetime_filter` (:203) | | `_convert_date_format` does naive `split("-")` — no clock use, deterministic |

### 3.4 `mixpanel_headless._internal.validation` (Layer-1 arg + Layer-2 bookmark validators)

Direct covering tests: tests/unit/test_validation.py (**101**),
test_validation_pbt.py (**13**), test_bookmark_validation_pbt.py (**8**);
facade-level: tests/test_validation_funnel.py (**129**),
test_validation_retention.py (**107**), test_validation_flow.py (**116**),
test_validation_cohort.py (**22**), test_validation_bypass.py (**20**),
test_validation_bypass_r2.py (**16**). Output: `list[ValidationError]` always
(never raises).

| Function | Signature (condensed; full in JSON) |
|---|---|
| `validate_time_args` (:511) | `(*, from_date, to_date, last) -> list[ValidationError]` |
| `validate_group_by_args` (:650) | `(*, group_by) -> list[ValidationError]` |
| `validate_funnel_args` (:779) | `(*, steps, conversion_window, conversion_window_unit="day", math=..., math_property=None, exclusions, holding_constant=None, from_date, to_date, last, group_by, reentry_mode=None, data_group_id=None)` |
| `validate_retention_args` (:1179) | `(*, born_event, return_event, retention_unit="week", alignment="birth", bucket_sizes=None, math=..., mode="curve", unit="day", from_date=None, to_date=None, last=30, group_by=None, unbounded_mode=None, data_group_id=None)` |
| `validate_flow_args` (:1498) | `(*, steps: list[str], forward=3, reverse=0, count_type="unique", mode="sankey", cardinality=3, conversion_window=7, conversion_window_unit="day", from_date=None, to_date=None, last=30, time_comparison=None, data_group_id=None)` |
| `validate_flow_bookmark` (:1772) | `(params: dict) -> list[ValidationError]` |
| `validate_query_args` (:1885) | `(*, events, math, math_property, per_user, percentile_value=None, from_date, to_date, last, has_formula, rolling, cumulative, group_by, formulas=None, data_group_id=None)` |
| `validate_bookmark` (:2288) | `(params: dict, *, bookmark_type: str="insights") -> list[ValidationError]` |
| `validate_sorting_block` (:3036) | `(sorting: Any) -> list[ValidationError]` |
| `contains_control_chars` (:346) | `(s: str) -> bool` |
| `_scan_custom_properties` (:218) | private but called directly by workspace.py (2691, 3012, 3803, ~4170) — de-facto contract surface |

**Hazard (all validators): `_suggest` (validation.py:410) uses
`difflib.get_close_matches` (import at :19)** — "did you mean" suggestion lists
in `ValidationError` messages/details depend on difflib's SequenceMatcher
ratios. TS port must either reimplement difflib ratio semantics or the vector
comparator must mask suggestion substrings. Error *codes* and *paths* are safe
comparison keys; message text also embeds Python type names
(`type(x).__name__`, e.g. workspace.py:2603).

### 3.5 `mixpanel_headless._internal.bookmark_schema` (Pydantic Layer-2)

Covering tests: tests/unit/test_bookmark_schema.py (**47**),
test_bookmark_schema_pbt.py (**14**), tests/integration/test_bookmark_schema_roundtrip.py.

| Function | Signature | Hazards |
|---|---|---|
| `validate_with_pydantic` (:170) | `(model_cls: type[BaseModel], raw: Any, *, code_mapper: CodeMapper\|None=None, path_prefix: str="") -> list[ValidationError]` | **error-message text is Pydantic-version-dependent** — vectors should assert on translated `code` + JSONPath, not raw message |
| `get_root_model_for_bookmark_type` (:333) | `(bookmark_type: str) -> type[BaseModel]\|None` | returns a *class* — vector-encode as model name string |
| discriminators (pure str fns): `_flat_sort_discriminator` (:425), `_sort_config_discriminator` (:500), `_flat_or_column_sort_discriminator` (:547), `_table_sort_discriminator` (:609), `_show_clause_discriminator` (:1200); mappers `_default_code_mapper` (:110), `_sorting_code_mapper` (:124), `_translate_pydantic_error` (:223), `_loc_to_jsonpath` (:274) | | pure |
| ~40 Pydantic models (`InsightsBookmarkParams` :1419, `FlowsBookmarkParams` :1501, `Sections` :1238, `Behavior` :1025, …) | | schema itself is the contract; port as zod/valibot schemas, verified through `validate_with_pydantic` vectors |

### 3.6 `mixpanel_headless._internal.bookmark_enums`

**Zero functions** — 38 module-level `frozenset`/`dict` constants
(`VALID_MATH_TYPES` :23 … `VALID_FREQUENCY_FILTER_OPERATORS` :594,
`MAX_CONVERSION_WINDOW` :501). Covering tests: tests/unit/test_bookmark_enums.py
(**39**). Not vector material per se (constants), but each constant's contents
should be snapshot into the corpus once so drifts fail loudly.

### 3.7 `mixpanel_headless._internal.query.user_builders` / `user_validators`

Covering tests: tests/test_user_builders.py (**51**), test_user_validators.py
(**149**), test_query_user_edge_cases.py (**28**), test_query_user_structural.py
(**13**), test_user_query_pbt.py (**29**).

| Function | Signature | Output | Hazards |
|---|---|---|---|
| `filter_to_selector` (user_builders.py:82) | `(f: Filter) -> str` | selector str | translation path #3; string-escaping fuzz target (plan:496); raises `ValueError` on unsupported ops |
| `filters_to_selector` (user_builders.py:222) | `(filters: list[Filter]) -> str` | selector str | — |
| `extract_cohort_filter` (user_builders.py:251) | `(filters: list[Filter]) -> tuple[list[Filter], Filter\|None]` | tuple | — |
| `validate_user_args` (user_validators.py:58) | 20-kwarg keyword-only, `-> list[ValidationError]` (full signature in JSON) | list[ValidationError] | **`date.today()` at user_validators.py:211,217** (as_of future check) |
| `validate_user_params` (user_validators.py:479) | `(params: dict) -> list[ValidationError]` | list[ValidationError] | parses the `filter_by_cohort` JSON string (imports `json`, user_validators.py:17) — pure |
| private: `_format_value` (:26), `_prop_ref` (:44), `_is_cohort_filter` (:63), `_normalize_filters` (user_validators.py:37) | | | |

### 3.8 `mixpanel_headless._internal.expressions`

| Function | Signature | Tests |
|---|---|---|
| `normalize_on_expression` (:15) | `(on: str) -> str` | tests/unit/_internal/test_expressions.py (**27** collected from 10 defs — parametrized), test_expressions_pbt.py (**6**) |

Pure regex/string; zero imports beyond stdlib typing. Ideal first vector target.

### 3.9 `mixpanel_headless._internal.transforms`

| Function | Signature | Output | Tests | Hazards |
|---|---|---|---|---|
| `transform_event` (:21) | `(event: dict) -> dict` | dict **containing a `datetime` object** (`event_time`, transforms.py:67) | indirect only: tests/unit/test_workspace_streaming.py (20), test_live_query_pbt.py (10) — **no dedicated unit file; coverage gap** | **`uuid.uuid4()` at transforms.py:71** when `$insert_id` missing; datetime output needs an ISO-encoding rule in the vector schema. Deterministic iff input has `$insert_id`. |
| `transform_profile` (:88) | `(profile: dict) -> dict` | plain dict | tests/test_query_user_structural.py (13, imports it at :31) | none — fully pure |

### 3.10 `mixpanel_headless.replay_labels` (public)

| Function | Signature | Tests | Hazards |
|---|---|---|---|
| `url_normalizer` (:39) | `(url: str) -> str` | tests/unit/test_replay_bundle.py (28 collected; 16 direct mentions), test_rrweb_analyzer.py (50 collected; 5 mentions) | regex `_NUMERIC_OR_HEX` (:37) — port regex semantics carefully |
| `default_label_fn` (:86) | `(action: UserAction) -> str` | same files | input is a `UserAction` dataclass — vector schema needs its dict form |
| `selector_label_fn` (:114) | `(attr: str="data-testid") -> Callable[[UserAction], str]` | same files | **returns a closure** — vector must record `(attr, action) -> str`, i.e. test the returned function, not the factory value |

### 3.11 Boundary entries (pure, in delegation chains, owned by types.py)

- `mixpanel_headless.types._sanitize_raw_cohort(raw: dict) -> dict`
  (types.py:8997) — called from bookmark_builders.py:444, workspace.py:2099 and
  :9189, types.py:7733. Pure dict scrub.
- `CohortDefinition.to_dict()` + cohort-behavior serializers (types.py) — pure;
  covered by tests/unit/test_cohort_definition.py (**80**),
  tests/test_cohort_definition_pbt.py (**16**), test_types_cohort_behaviors.py
  (**74**), test_cohort_behaviors_pbt.py (**17**). Formally type-serialization
  scope, but `build_params`/`build_user_params` vectors flow through them.

## 4. Totals and top-20 by covering-test count

One-shot `pytest --collect-only` over the 38 builder-related files:
**1,723 collected** (command in `builder-registry.json` `.totals.collect_command`).

Top-20 entries ranked by primary covering-test count (collected; file-level
attribution, so facade/validator pairs share files — see JSON for the mapping):

| # | Entry | Primary tests |
|---|---|---|
| 1 | `Workspace.build_params` | ~396 (test_query_params 86 + query_pbt 28 + query_validation 76 + query_validation_pbt 4 + query_integration 22 + build_cohort_params 67 + custom_property_{builders,types,query,pbt} 93 + bypass 20) |
| 2 | `validation.validate_*` (module, direct) | 122 (test_validation 101 + validation_pbt 13 + bookmark_validation_pbt 8) |
| 3 | `user_validators.validate_user_args`/`validate_user_params` | 149 (test_user_validators) |
| 4 | `validation.validate_funnel_args` | 129 (test_validation_funnel) |
| 5 | `bookmark_builders.*` (direct) | 117 (test_bookmark_builders 109 + pbt 8) |
| 6 | `validation.validate_flow_args`/`validate_flow_bookmark` | 116 (test_validation_flow) |
| 7 | `validation.validate_retention_args` | 107 (test_validation_retention) |
| 8 | `Workspace.build_funnel_params` | 77 (test_build_funnel_params) |
| 9 | `Workspace.build_user_params` | 68 (test_workspace_build_user_params) |
| 10 | `bookmark_schema.validate_with_pydantic` (+models) | 61 (test_bookmark_schema 47 + pbt 14) |
| 11 | `user_builders.filter_to_selector`/`filters_to_selector` | 51 (test_user_builders) |
| 12 | `Workspace.build_flow_params` | 49 (test_workspace_flow) |
| 13 | `segfilter.build_segfilter_entry` | 49 (test_segfilter) |
| 14 | `Workspace.build_retention_params` | 39 (test_build_retention_params) |
| 15 | `bookmark_enums` constants | 39 (test_bookmark_enums) |
| 16 | `expressions.normalize_on_expression` | 33 (27 + 6 pbt) |
| 17 | user-query edge/structural/pbt (shared: build_user_params + selectors) | 70 (28 + 13 + 29) |
| 18 | `validation` cohort path (via build_params) | 22 (test_validation_cohort) |
| 19 | `replay_labels.{url_normalizer,default_label_fn,selector_label_fn}` | ~21 direct assertions inside test_replay_bundle/test_rrweb_analyzer (78 collected total in those files) |
| 20 | bypass/equivalence/roundtrip guards (facade≡module invariants) | 49 (bypass 20 + bypass_r2 16 + delegation_equivalence_pbt 6 + roundtrip_soundness_pbt 7) |

## 5. Determinism hazard summary (corpus-design checklist)

1. **Clock**: `bookmark_builders.build_date_range` (bookmark_builders.py:114)
   and `user_validators.validate_user_args` (user_validators.py:211,217) call
   `date.today()`. Record-mode must freeze the clock (freezegun/env-pinned
   date) or restrict vectors to explicit-date inputs.
2. **UUID**: `transforms.transform_event` (transforms.py:71) generates
   `uuid.uuid4()` when `$insert_id` absent. Vectors: always supply `$insert_id`,
   or comparator ignores `insert_id`.
3. **Non-JSON output values**: `transform_event` returns a `datetime`
   (transforms.py:67); engage params embed a JSON-string (`filter_by_cohort`,
   workspace.py:9186-9190); `get_root_model_for_bookmark_type` returns a class.
   Vector schema needs explicit encoding rules for each.
4. **difflib suggestions**: `validation._suggest` (validation.py:410) — mask or
   reimplement; compare on `code` + `path`, treat `message` as advisory.
5. **Pydantic error text**: `bookmark_schema.validate_with_pydantic` — pin
   Pydantic version at record time; compare translated codes/paths only.
6. **Python type names in messages**: e.g. `type(events).__name__`
   (workspace.py:2603) → `"list"`/`"tuple"` never match TS. Same masking rule
   as (4).
7. **Dict order**: all builders assemble dicts in fixed insertion order; no
   sorting anywhere — comparator must be key-order-insensitive JSON equality.
8. **No randomness/env/network in any builder path** (import audit: only `re`,
   `difflib`, `datetime`, `json`, `logging`, `uuid`, `pydantic` across the nine
   modules).
