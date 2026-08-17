# Python bugfix batch — FIX-1 notes (bugs (a) frequency-filter clause shape, (b) dataGroupId threading)

Branch: `ts-port/python-bugfix-batch` (created from `ts-port/phase2-contract-support` @ c2a25c5).
Task: FIX-1 of the R10.7 four-bug batch (inbound-ledger row 2, playbook P3-7 trigger 3).

## Correct-shape derivation (analytics oracles, READ-ONLY)

### Bug (a) — frequency filter clause (fix-of-record: `context/phase1/addendum/frequency-filter-probe.md` + `context/phase1/bug-reports/mixpanel-headless-frequency-filter-clause-shape.md`)

The fix-of-record names the platform-native shape (top-level `filterType`/`filterOperator`/
`filterValue`, `$frequency` under `behavior.behaviorType`) but leaves field-level details
(event object, label, dateRange, event-filter placement) to the oracles. Derivation:

- Primary fixture: `analytics/api/version_2_0/insights/test.py:4111` region
  (`test_multi_metric_bar_and_table_chart_csv_exports`) — the native clause is:
  `{"behavior": {"aggregationOperator": "total", "behaviorType": "$frequency", "dateRange": null,
  "event": {"label": ..., "value": ...}, "filters": [], "filtersOperator": "and"},
  "dataGroupId": null, "dataset": "$mixpanel", "defaultType": "number",
  "filterOperator": ..., "filterType": "number", "filterValue": N, "profileType": null,
  "propertyObjectKey": null, "resourceType": "people", "search": "", "value": "<label>"}`.
  Corroborated by `test_behaviors.py:2225-2247` (identical clause via `behavior_filter`)
  and the production migration `bookmark_parser/common/transforms/util.py:355-390`
  (`_create_frequency_behavior_group` — same behavior-dict spelling).
- Deep validator (`analytics/bookmark_parser/insights/validate.py`):
  `insights_filter_section_validator` (module-level `required=True`, `extra=ALLOW_EXTRA`)
  requires top-level `filterType` + `filterOperator`; `behavior` validated by
  `behavior_validator` (`:188`).
- Display label: native shape carries it in top-level `value` (fixtures use
  `"<Event> Frequency"`); no separate `label` key — mirrors the library's own
  `build_frequency_group_entry` (label → `value`).
- Event filters: native placement is `behavior.filters` (list of standard filter entries,
  `filtersOperator: "and"`) — NOT the old `behavior.eventFilters`.
- dateRange for `date_range_value`/`date_range_unit` ("in the last N units"):
  `{"type": "in the last", "unit": u, "window": {"unit": u, "value": N}}` — derived from
  `date_range_validator` (= `TIME_VALIDATION_SCHEMA.extend({"type": str, "unit": ..., Optional("value")})`,
  `window: TIME_OFFSET_SCHEMA` = `{"unit", "value"}`) + fixtures `test_behaviors.py:4014`
  (`{"type": "in the last", "unit": u}`) and `:15478` (`window: {"unit": "day", "value": 3}` spelling).
- ajv referee (a) does NOT constrain filter clauses (`Sections.filter` is `JsonValue[]` in
  `vendor/mixpanel-contracts/bookmark.json`) — the deep referee (b) is the binding oracle here.
- EMPIRICAL ACCEPT (pre-implementation probe, referee-(b) recipe env,
  `PYTHONPATH=/Users/jaredmcfarland/Developer`, voluptuous==0.16.0):
  `validate_insights_bookmark_params_schema(..., require_all_keys=False)` ACCEPTs all three
  candidate variants (basic, in-the-last window dateRange, event filters in `behavior.filters`).

### Bug (b) — dataGroupId threading (fix-of-record: `context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md`)

- Clause level (`GroupClause.dataGroupId`): `string | null` in BOTH oracles
  (ajv `DataGroupId = anyOf[string, null]`; deep `Optional("dataGroupId"): Any(None, str)`).
  Fix choice (doc offers either): keep `int | None` parameter annotations, emit
  `str(data_group_id)` at emission (None stays None).
- INTERIOR cohort-entry `data_group_id` (inside `GroupClause.cohorts[]`): deep validator is
  `Any(int, str, None)` BUT ajv `GroupByCohort.data_group_id` is `DataGroupId | null` =
  string|null — so the interior emission MUST also coerce to str for referee (a) to run
  fully clean. (The bug report's pinned error substring only names the clause path, but the
  pin is substring-matched; the interior int would keep ajv red post-fix.)
- Sections level: the ajv `Sections` model (`additionalProperties: false`) has NO `dataGroupId`;
  the correct spelling is `globalDataGroupId: string | null`. Analytics' own fixture
  `test_behaviors.py:15109` emits `"globalDataGroupId": str(self.data_group_id)` in `sections` —
  confirming BOTH the key spelling and the str coercion. Deep validator: sections is a nested
  raw dict under the top-level `extra=REMOVE_EXTRA` schema → unknown `globalDataGroupId` is
  stripped, ACCEPT (empirically confirmed in the same probe run).
- Out of scope: `workspace.py:3612` `params["data_group_id"]` is a snake_case legacy funnels
  QUERY param (not bookmark sections) — not named by the fix-of-record; untouched.
- Emission sites fixed: `bookmark_builders.py` build_group_section (CustomPropertyRef entry,
  InlineCustomProperty entry), `_build_cohort_group_entry` (interior `data_group_id` +
  clause `dataGroupId`), `build_frequency_group_entry` (`dataGroupId`); `workspace.py`
  `sections["dataGroupId"]` → `sections["globalDataGroupId"] = str(...)` at the three
  bookmark-sections sites (insights `_build_query_params` region :2278, funnel :2923,
  retention :3457).

## TDD red runs

Both bugs strictly red-first: tests were rewritten to the derived correct shapes and run
BEFORE any implementation change.

### Bug (a) red run (2026-08-16)

`env -u FORCE_COLOR -u COLORTERM uv run pytest tests/unit/test_bookmark_builders.py::TestBuildFrequencyFilterEntry tests/unit/test_bookmark_builders.py::TestBuildFilterSectionFrequency tests/unit/test_query_params.py::TestFrequencyFilterInBuildParams -o addopts="" -q`
→ **14 failed, 1 passed** (the 1 pass = `test_existing_filter_still_works`, a plain-Filter
backward-compat case untouched by the bug). Failures: all 10 `TestBuildFrequencyFilterEntry`
tests, both `TestBuildFilterSectionFrequency` frequency tests, both
`TestFrequencyFilterInBuildParams` frequency tests.
GREEN after fixing `build_frequency_filter_entry`: 15 passed.

### Bug (b) red run (2026-08-16)

`env -u FORCE_COLOR -u COLORTERM uv run pytest tests/unit/test_bookmark_builders.py -k data_group tests/unit/test_query_params.py::TestDataGroupIdInsights tests/test_build_retention_params.py::TestDataGroupIdRetention tests/test_build_funnel_params.py::TestDataGroupIdFunnel -o addopts="" -q`
→ **9 failed, 7 passed** (fails = every with-data_group_id case across
frequency-group / custom-property-ref / inline / cohort clause+interior /
insights `globalDataGroupId` / `_build_query_params` / funnel / retention;
passes = without-/default-None cases + string-group + none-group).
GREEN after the emission coercions + `globalDataGroupId` rename: 16 passed.

Follow-on sweep: `tests/live/test_040_query_completeness_live.py` OFFLINE param-shape
assertions (M41/M42/M43/M45, X06) pinned the old `sections.dataGroupId` int spelling —
updated to `globalDataGroupId`/str (M44 asserts the snake_case flows `data_group_id`
QUERY param, out of scope, untouched).

## Conformance failing-vector inventory (RE-PIN task input)

`env -u FORCE_COLOR -u COLORTERM uv run python -m conformance.runner --vectors conformance/vectors --report json`
(post-fix, vectors UNTOUCHED per task scoping — the RE-PIN task owns re-extraction):

**status `vector_failed` — total 3,251 / passed 3,231 / failed 20** (exit 1). The 20
failures are EXACTLY the vectors that recorded the two buggy shapes — no collateral:

Bug (a) — frequency-filter clause shape (13):
- `filters/bookmark_builders.build_frequency_filter_entry/test_bookmark_builders-testbuildfrequencyfilterentry-test_basic_structure`
- `…-test_custom_operator`
- `…-test_label_included`
- `…-test_label_omitted_when_none`
- `…-test_multiple_event_filters`
- `…-test_with_date_range`
- `…-test_with_event_filters`
- `…-test_without_date_range`
- `…-test_without_event_filters`
- `filters/bookmark_builders.build_filter_section/test_bookmark_builders-testbuildfiltersectionfrequency-test_frequency_filter_in_filter_section`
- `…-test_mixed_filter_and_frequency`
- `bookmarks/workspace.build_params/test_query_params-testfrequencyfilterinbuildparams-test_frequency_filter_in_filter_section`
- `…-test_frequency_filter_mixed_with_filter`

Bug (b) — dataGroupId threading (7):
- `bookmarks/bookmark_builders.build_group_section/test_bookmark_builders-testbuildgroupsectiondatagroupid-test_cohort_breakdown_group_with_data_group_id`
- `…-test_custom_property_ref_group_with_data_group_id`
- `…-test_inline_custom_property_group_with_data_group_id`
- `bookmarks/bookmark_builders.build_group_section/test_bookmark_builders-testbuildgroupsectionfrequency-test_data_group_id_threaded_to_frequency`
- `bookmarks/workspace.build_params/test_query_params-testdatagroupidinsights-test_build_params_with_data_group_id`
- `funnels/workspace.build_funnel_params/test_build_funnel_params-testdatagroupidfunnel-test_build_funnel_params_with_data_group_id`
- `retention/workspace.build_retention_params/test_build_retention_params-testdatagroupidretention-test_build_retention_params_with_data_group_id`

Full JSON report copy saved during the run at `/tmp/conformance-postfix.json` (ephemeral);
the failure list above is the durable record. Runner and vectors NOT modified.
Post-fix confirmation: the ACTUAL new builder outputs (not just hand-built candidates) —
frequency filter basic / windowed / event-filters+label, and group sections for
custom-property-ref / cohort-breakdown / frequency-breakdown with `data_group_id` — all
ACCEPT under `validate_insights_bookmark_params_schema` (referee-(b) recipe env). The
referee handoff producer (`conformance/tests/test_referee_routing.py::TestProduceHandoff::
test_handoff_covers_all_bookmark_builder_vectors`) drift-aborts by design against the
stale vectors — regenerating `handoff.jsonl` + full referee re-runs belong to the RE-PIN
task after re-extraction.
Consequence for `just check` on this branch: every gate is green EXCEPT the `conformance`
recipe's corpus step, which reds on exactly these 20 vectors by design until the RE-PIN
task re-extracts and re-pins (playbook P3-7 trigger 3 choreography).

---

# FIX-2 notes (bugs (c) _handle_response 403 TypeError, (d) OAuth error-details token-payload leak)

Task: FIX-2 of the R10.7 four-bug batch, same branch `ts-port/python-bugfix-batch`.
Fix-of-record docs read in full:
- (c) `context/phase3/bug-reports/python-handle-response-403-typeerror.md`
- (d) `context/phase3/bug-reports/python-oauth-error-details-token-payload.md`

## Bug (c) — 403 sniff crash on truthy non-dict/non-str JSON bodies

Fix (report's suggested shape, verbatim semantics): `api_client.py` `_handle_response`
403 branch now computes
`body_text = response_body if isinstance(response_body, str) else ("" if response_body is None else json.dumps(response_body))`
— uniform SUBSTRING semantics across dict/list/scalar bodies, no TypeError possible.
Behavior deltas (all per the report's defect list):
- truthy scalars (`42`/`1.5`/`true`): uncoded TypeError → `QueryError` (Permission denied path);
- list bodies: element-membership → serialized substring sniff, so
  `["...SESSION_RECORDING_SENSITIVE_DATA..."]` now maps to `SessionReplayAccessError`
  (exact-element case unchanged);
- falsy scalars (`0`/`false`/`null`) and dict/str bodies: unchanged.
R5.4: no error CODE changed; `SessionReplayAccessError` details/message untouched;
all other status branches untouched.

### Red run (2026-08-16)

`env -u FORCE_COLOR -u COLORTERM uv run pytest "tests/unit/_internal/test_api_client_sign_replays.py::TestSensitiveData403BodyShapes" -o addopts="" -q`
→ **4 failed, 5 passed** BEFORE the fix (fails: truthy-scalar 42/1.5/True + list-substring;
passes: falsy scalars, list-exact, string-body — the already-correct branches).
GREEN after the one-expression fix: 9 passed (41 passed across the whole file + the
exceptions test file).

## Bug (d) — OAuthError details carried the full 200 token payload

Fix (report's first-listed recommendation: dict-shape REDACTION, not removal —
keeps field names + non-secret values for diagnosis): `flow.py`
`_post_token_request` missing-required-fields branch now emits
`details={"response_data": str({k: "<redacted>" if k in _TOKEN_BEARING_KEYS else v, ...})}`
with module constant `_TOKEN_BEARING_KEYS = frozenset({"access_token", "refresh_token", "id_token"})`.
Security rationale added as a `Security:` section in the `_post_token_request`
docstring (live bearer material never passes through `Secret`; serializing error
details would exfiltrate it into logging/telemetry/browser error reporters).
SUCCESS path untouched; error codes untouched (`OAUTH_TOKEN_ERROR` /
`OAUTH_REFRESH_ERROR` flow through the existing `error_code` parameter).
TS twin (`packages/core/src/auth/oauth-http.ts:245`) NOT touched here — retires with
the coordinated TS task per R10.7 (README/JSDoc caveats to be updated then).

### Red run (2026-08-16)

`env -u FORCE_COLOR -u COLORTERM uv run pytest "tests/unit/test_auth_flow.py::TestTokenPayloadRedaction" -o addopts="" -q`
→ **3 failed, 1 passed** BEFORE the fix (fails: exchange-path leak, refresh-path leak
incl. `id_token`, non-secret-visibility; passes: `test_success_path_unchanged` — the
success-path guard, expected green pre-fix).
GREEN after the fix: whole `tests/unit/test_auth_flow.py` → 43 passed.

## Conformance failing-vector inventory for (c)/(d) — APPEND per task

`env -u FORCE_COLOR -u COLORTERM uv run python -m conformance.runner --vectors conformance/vectors --report json`
(post-FIX-2, vectors UNTOUCHED): **total 3,251 / passed 3,231 / failed 20** — the
failing set is IDENTICAL to the FIX-1 inventory above (13 bug-(a) + 7 bug-(b) vectors).

**Bug (c): ZERO failing vectors.** Stated explicitly: no corpus vector exercises the
403 truthy-scalar / list-body crash path (matches the fix-of-record: B0-2 coverage is
Layer-3 + TS edge harness, not vectors — the fix window was open and no recorded
vector locked the buggy branch).

**Bug (d): ZERO failing vectors.** The 7 `oauth_flow.` vectors all still PASS —
none asserts `details["response_data"]` content (the report predicted this;
confirmed empirically here). No re-pin strictly required for (d), but the RE-PIN
task re-extracts wholesale anyway.

## Gate (FIX-2 run record, 2026-08-16)

`env -u FORCE_COLOR -u COLORTERM just check`: lint / fmt-check / typecheck /
docstring-cov / test-cov ALL GREEN (7,130 passed, 1 skipped; coverage 92.33% >= 90%).
The `conformance` recipe reds EXACTLY as documented in the FIX-1 gate note: its first
step (`pytest conformance/tests`) fails only on
`test_referee_routing.py::TestProduceHandoff::test_handoff_covers_all_bookmark_builder_vectors`
(the by-design drift-abort against the stale pre-RE-PIN vectors; 517/518 pass), which
short-circuits the recipe's corpus step — the corpus was therefore run manually
(inventory above: same 20 FIX-1 vectors, ZERO from (c)/(d)). `just build` was run
separately after the conformance short-circuit: GREEN (sdist + wheel built).
FIX-2 adds ZERO new gate failures; everything red is the known FIX-1 re-pin debt
owned by the RE-PIN task.

---

# RE-PIN notes (the single corpus re-pin event for the four-bug batch)

Task: REPIN (inbound-ledger row 2 choreography / playbook P3-7 trigger 3), same branch.
Status: IN PROGRESS — sections filled as steps complete.

## Step 1 — re-record

Command (record README D3 form, via `just conformance-record`):
`env -u FORCE_COLOR -u COLORTERM just conformance-record --mp-record-date=2026-08-16 --mp-record-commit=700db996cc952e02aa5a23db1f3c68a3e7251b5b`
New pin = `700db99` (`700db996cc952e02aa5a23db1f3c68a3e7251b5b`) — the branch HEAD carrying
FIX-1 (bddc576) + FIX-2 (57c5e16) + their notes commits; stamps injected, never wall-clock.
Record run: `[mp-record] wrote 3042 vectors in 157 bundles` (7,157 passed, 1 skipped,
556 deselected). Recorded total 3,031 → 3,042.

## Step 2 — D8/D9 drift accounting (CLEAN, every changed file accounted)

Mechanical per-vector accounting (script diffed each changed bundle against `HEAD`,
bucketing stamp-only vs modified/added/removed vector ids against the FIX-1/FIX-2
20-vector inventory): 158 changed files =
- **150 bundles stamp-only** (`$bundle.source_commit` line only);
- **manifest.json** (stamps + the deltas below);
- **7 bundles with vector content changes**, containing EXACTLY the disclosed
  **20 MODIFIED** vectors (13 bug-(a) + 7 bug-(b), the FIX-1 inventory verbatim — all
  20 matched, none missing) plus **11 ADDED** vectors, each traced to a new test from
  the batch:
  - bug (a) +1: `filters/bookmark_builders.build_frequency_filter_entry/...-test_no_custom_property_nesting` (FIX-1 new test);
  - bug (b) +0 (its new tests recorded into existing modified vectors);
  - bug (c) +9: `replays/api_client.sign_replays/...-testsensitivedata403bodyshapes-*` (falsy 0/false/null, truthy 42/1.5/true, list-exact, list-substring, string-body);
  - bug (d) +1: `auth/oauth_flow.refresh_tokens/...-testtokenpayloadredaction-test_refresh_missing_fields_error_redacts_token_material`.
- **0 REMOVED, 0 UNEXPLAINED.**

Manifest deltas beyond stamps (all traced): by_capability auth 39→40, filters 190→191,
replays 94→103; by_kind builder 1768→1769, wire 1198→1208; total 3,031→3,042;
`raw_transport_no_entrypoint` 34→37 — the three new exclusions are
`TestTokenPayloadRedaction::{test_exchange_missing_fields_error_redacts_token_material,
test_non_secret_fields_stay_visible, test_success_path_unchanged}` (exchange path has no
recordable entrypoint, matching the standing `TestOAuthFlowTokenExchange` exclusions).

## Step 3 — P3-0 vector-count re-measurement

Full-corpus per-prefix measurement (P3-0 command form over `conformance/vectors`):
total **3,262** = 3,251 + Δ11. Per-bug Δ: (a) +1, (b) +0, (c) +9, (d) +1.
Prefix deltas EXACTLY: `bookmark_builders` 134→135, `api_client` 810→819,
`oauth_flow` 7→8 (old values re-measured from HEAD-committed vectors, not assumed);
every other prefix unchanged. Playbook P3-0 updated with the re-pin bullet
(`70c904d` → `700db99`).

## Step 4 — Python conformance runner @ new pin

`env -u FORCE_COLOR -u COLORTERM uv run python -m conformance.runner --vectors conformance/vectors --report json`
→ exit 0, **total 3,262 / passed 3,262 / failed 0** (N/0/0).

## Step 5 — referee (b) FULLY CLEAN (the 2 deep REJECTs retire)

- Handoff regenerated: 314 entries (live re-execution under replay clock, zero drift
  aborts — the re-recorded vectors match live rebuild).
- Selftests first, both oracles: `status: ok` (structural 3/3, deep 4/4 controls).
- Structural batch: **314/314 ACCEPT, 0 REJECT**, exit 0 (dialects unchanged:
  251 modern-nested / 47 legacy-flat / 16 neutral).
- Deep batch: **125 ACCEPT / 0 REJECT / 189 SKIP_NON_INSIGHTS**, exit 0 — the 2
  standing frequency-filter deep REJECTs
  (`testfrequencyfilterinbuildparams-test_frequency_filter_in_filter_section` /
  `…-test_frequency_filter_mixed_with_filter`) are RETIRED.
- Standing-disclosure pin removed: referee README "Batch results" section rewritten
  (no expected-REJECT set remains on the Python side; any future REJECT = new finding).
  No code-level allowlist existed on the Python side (verified by grep).
- `/Users/jaredmcfarland/Developer/analytics` used READ-ONLY (PYTHONPATH recipes only).
- NOT in scope here: the ajv referee (a) pinned dataGroupId REJECT set lives in the TS
  repo and retires with the TS follow-up task (R10.7 flip discipline).
