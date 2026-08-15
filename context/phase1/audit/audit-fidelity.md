# Phase-1 Audit — Lens 3: Vector Fidelity

Auditor: independent (not the builder). Date: 2026-08-14.
Branch: `ts-port/phase1-verification-rig` @ 63db3b0.
Sample seed: 20260814 (stratified draw script recorded inline below in §A).

Corpus ground truth measured by auditor (excluding `$bundle` header lines):
- 2,609 vectors total = 2,530 extracted (matches manifest.counts.total) + 79 authored.
- Kinds: wire 1,178, builder 1,361, parse 6, validation-error 64 (manifest by_kind covers the
  extracted subset only: builder 1302 + wire 1164 + validation-error 64 = 2530; the deltas are
  the authored vectors).
- with_setup = 116 (matches manifest), multi-interaction vectors = 98.

## A. 40-vector stratified fidelity sample

Strata: 14+ wire (incl. 2 with `call.setup[]`, 2+ multi-interaction), 14 builder,
4 validation-error, 2 parse, 8 from `authored/`; 17 capabilities covered.

Findings recorded per vector below. Verdicts: FAITHFUL / WEAKENED / MISENCODED.
Independent full-corpus re-run: `uv run python -m conformance.runner --vectors
conformance/vectors --report json` → **2609/2609 passed, 0 failed, 1.17 s** (so every
sampled vector's encoding is executable and matches live Python behavior; fidelity
questions below are therefore about *coverage of the source test's contract*, not
correctness of what IS encoded).

| # | Vector id (abbrev) | Kind | Verdict |
|---|---|---|---|
| 0 | entities/workspace.restore_feature_flag/...test_restore_feature_flag | wire+setup | FAITHFUL — setup encodes `set_workspace_id(100)` from `_make_workspace`; two-session D5.1 pattern present; result is full FeatureFlag (superset of test's 3 asserts) |
| 1 | discovery/api_client.get_events/...test_use_project_clears_pin_from_query_params | wire+setup | **WEAKENED** — see Finding F1 |
| 2 | pagination/paginate_all/...test_http_401_mid_pagination | wire multi | FAITHFUL — test asserts only `raises(AuthenticationError)`; vector adds code+details_contain+both exact request param sets |
| 3 | pagination/paginate_all/...hostile_retry_after[thousands-separator] | wire multi | FAITHFUL w/ documented exclusion — `durations == [1.0]` sleep-math is Layer-3 by design (ledger `layer3_deferred` row, design D2 exclusion 1); request sequence + result + no-crash contract encoded |
| 4 | bookmarks/build_time_section/authored-from-only-today-fill-record-epoch | builder authored | FAITHFUL — record-epoch (2026-01-15) today-fill matches manifest record_epoch; passes runner |
| 5 | compat/wirestub.request_sequence/authored-multi-interaction | wire authored | FAITHFUL — harness self-test; ordered 2-interaction sequence w/ json_body + content-type |
| 6 | streaming/_iter_jsonl_lines/authored-crlf-line-endings | builder authored | FAITHFUL — b64 decodes to `{"a": 1}\r\n{"b": 2}\r\n`, output CR-stripped lines; verified by runner |
| 7 | validation/validate_bookmark/authored-b20b-filter-value-not-finite-list | builder authored | FAITHFUL — `$type:float "-Infinity"` codec used for non-finite input (D6 rule 5 makes raw non-finite illegal); B20B code+path+severity |
| 8 | parse/workspace.activity_feed/authored-phase008-activity-feed | parse | FAITHFUL — full request body incl. bookmark envelope + parsed result |
| 9 | parse/workspace.segmentation_numeric/authored-phase008 | parse | FAITHFUL |
| 10 | funnels/build_funnel_params/...test_invalid_cp_id_raises | validation-error | FAITHFUL — `match="positive integer"` translated to structured `CP1_INVALID_ID` + path (documented D6.6/R5.4 translation) |
| 11 | bookmarks/build_params/...test_rejects_invalid_date_format | validation-error | FAITHFUL — `match="YYYY-MM-DD"` → `V8_DATE_FORMAT` + path `from_date` |
| 12 | bookmarks/build_params/...test_invalid_ref_in_metric | validation-error | FAITHFUL — `CP1_INVALID_ID` + path `events[0]` |
| 13 | bookmarks/build_params/...test_v27_metric_histogram_requires_per_user | validation-error | FAITHFUL — `V27_HISTOGRAM_REQUIRES_PER_USER` |
| 14 | data-governance/download_lookup_table/...test_with_file_name_and_limit | wire | FAITHFUL — bytes result `$type`-tagged (D6.11); exact params incl. dashed names (test only asserted `isinstance(result, bytes)`) |
| 15 | auth/projects_metadata_index/...test_returns_project_keyed_mapping | wire | FAITHFUL — session-relative auth pattern `^Basic dTpz$` for the `u`/`s` fake creds (D5.2 working as designed) |
| 16 | cohorts/bulk_update_cohorts/...test_bulk_update_cohorts_multiple | wire | FAITHFUL — exact json_body incl. per-entry key omission (test asserted nothing beyond "no raise") |
| 17 | bookmarks/list_bookmarks_v2/...test_filters_by_ids | wire | FAITHFUL — test asserts `"ids=" in url`; vector locks `ids=10,20`&`v=2` exactly |
| 18 | segmentation/segmentation_average/...hourly | wire | FAITHFUL |
| 19 | retention/retention/...default_interval_sends_unit_only | wire | FAITHFUL — `interval` absence preserved via exact-params equality (runner diffs the full param dict, execute.py `_REQUEST_CORE_KEYS`) |
| 20 | replays/fetch_files/...test_transport_error_redacts_signed_credential | wire multi | **WEAKENED** — see Finding F2 |
| 21 | discovery/get_property_values/...basic_call | wire | FAITHFUL — unsorted value order preserved |
| 22 | engage/export_profiles/...test_cohort_id_filter | wire | FAITHFUL — `filter_by_cohort` inner-JSON string locked char-exact (`'{"id": "12345"}'`) |
| 23 | flows/build_flow_params/...exclusions_none | builder | FAITHFUL — full 14-key output (test asserted 1 key) |
| 24 | compat/python_str/authored-bool-none-list | builder authored | FAITHFUL — `str([True, None])` pythonCompat pin |

Sample rows 25-39 (all FAITHFUL, spot notes):

| # | Vector | Verdict |
|---|---|---|
| 25 | streaming/transform_profile/...missing_distinct_id | FAITHFUL — exact 3-key output = the test's 3 asserts |
| 26 | bookmarks/build_params/...cohort_metric_has_show_section | FAITHFUL — test asserts `len(show) > 0`; vector locks full section tree |
| 27 | retention/build_retention_params/...has_display_options_key | FAITHFUL — full output incl. sorting/columnWidths |
| 28 | filters/build_filter_entry/...custom_property_ref_omits_value | FAITHFUL — `"value" not in entry` preserved by exact-output equality |
| 29 | segmentation/normalize_on_expression/...escapes_double_quotes | FAITHFUL — selector string char-exact incl. backslash escapes |
| 30 | validation/validate_retention_args/...zero_width_joiner R1 | FAITHFUL — test asserts `any(code==R1...)`; vector locks the exact single-error list |
| 31 | funnels/build_funnel_params/...reentry_mode_optimized | FAITHFUL |
| 32 | engage/build_user_params/...distinct_ids_passthrough | FAITHFUL — test tolerates str-or-list; vector pins the exact JSON-string form `'["user_1", "user_2", "user_3"]'` |
| 33 | replays/url_normalizer/...strips_query_string | FAITHFUL |
| 34 | cohorts/CohortDefinition.to_dict/...selector_and_behaviors | FAITHFUL — `$type:CohortDefinition` codec round-trips private fields |
| 35 | flows/build_flow_params/...flow_property_filter | FAITHFUL |
| 36 | validation/validate_query_args/authored-v23-rolling-too-large | FAITHFUL — authored, passes live |
| 37 | streaming/transform_profile/...completely_empty | FAITHFUL |
| 38 | bookmarks/build_params/...r2v3 finite_value_passes | FAITHFUL — `filterValue: 18` kept as int token (rule 3, not normalized — correct: bookmark filterValue is a rule-4 non-target) |
| 39 | retention/build_retention_params/...has_sections_and_display_options | FAITHFUL |

**§A verdict: 38/40 FAITHFUL, 2 WEAKENED (F1, F2 below). No MISENCODED.** The dominant
pattern is vectors being STRONGER than their source tests (full-output equality vs
spot asserts; exact param dicts vs substring checks) — the right direction under R10.2.

### Finding F1 (WEAKENED, minor): pin-lifecycle vectors lose the pinned-workspace precondition

`discovery/api_client.get_events/test_query_workspace_scoping-testpinlifecycle-test_use_project_clears_pin_from_query_params`
(and its sibling `...test_zero_axis_use_clears_pin_from_query_params`). The source test
constructs the client from `pinned_session` (workspace **777** pinned → `_workspace_id`
set), then calls `use(project="99999")` and asserts the pin is GONE from the next
request. The recorder captures `call.session` at MEASURED-call time (`emit.py`
`session = measured.session`), i.e. AFTER `use()` replaced the session — so the vector's
session has **no `workspace_id`** and the replay (runner `_ReplayContext.get_client` →
`build_session(call.session)`) starts pin-free. A TS port that fails to clear a stale
pin on `use()` would still pass: there is no pin to clear. The assertion text
(`workspace_id` absent from params) IS encoded via exact-params equality, but the
discriminating precondition is silently dropped, and neither EXTRACTION-LEDGER.md nor
the manifest documents it. Contrast: the sibling
`testqueryhostinjectionwhenpinned-test_pinned_workspace_get_includes_workspace_id`
vector DOES carry `workspace_id: 777` in `call.session` (the encoding supports pins),
so the fix is small: emit the PRE-setup session, or a `set_workspace_id` setup entry,
for tests whose client session mutates before the measured call. Blast radius measured:
2 vectors (the two `testpinlifecycle` ids). Mitigation already in place: the pin-clear
behavior remains covered by the Layer-3 translated tests (R10.1) when
`test_query_workspace_scoping.py` is ported — but the Layer-1 corpus does not lock it.

### Finding F2 (WEAKENED, minor): security message-content assertions are structurally dropped

`replays/replays.fetch_files/...test_transport_error_redacts_signed_credential`. The
source test's entire contract is message content: `signed.query_string not in
str(error)` and `"<redacted>" in str(error)`. D6 rule 6 drops `message` from every
error diff, so the vector encodes only `class: MixpanelHeadlessError, code:
CDN_FETCH_ERROR` — a TS port that leaks the CDN Signature in the error message passes
this vector. The message-drop is a documented GLOBAL rule (R5.4 "messages are
advisory"), but for this test the message is not advisory — it is a credential-hygiene
contract, and no exclusion-ledger entry or authored compensating vector flags it. Only
occurrence of this pattern found in the sample; corpus-wide the same class covers the
few `redact` tests in test_replays_service.py. Mitigation: Layer-3 translated tests
will carry the assertion; consider a `message_not_contains` schema field or a ledger
note if Layer-1 is meant to stand alone.

## B. Canonicalizer skepticism (canonical.py vs D6)

Read `conformance/runner/canonical.py` (533 lines) rule-by-rule against D6:

- **Rule 1** ✓ `sorted(value.keys())` = codepoint sort; no key filtering anywhere in
  `canonicalize`; absent ≠ null preserved (no `None`-dropping). Non-string keys reject.
- **Rule 2** ✓ `json.dumps(ensure_ascii=False)` = minimal-escape form matching
  `JSON.stringify`; lone surrogates rejected via `[\ud800-\udfff]` scan (correct in
  Python: any surrogate in a `str` is unpaired by construction).
- **Rule 3** ✓ `bool` checked before `int` (Python bool-is-int trap avoided); int
  renders `str(value)`; float renders via repr — `18.0` stays `"18.0"`, never unified.
- **Rule 4** — the over-normalization hunt: detection requires BOTH
  `selected_property_type == "number"` AND a `filter` mapping containing `operand`
  (`_is_number_filter_entry`). Verified by grep that `selected_property_type` is
  produced by exactly ONE library site (`segfilter.py:311`; the bookmark_schema.py hit
  is a validator `Ignore` field, not a producer), so the structural trigger cannot fire
  on bookmark `filterValue`, engage selectors, or arbitrary payloads. Explicit
  non-target selftest cases exist (`bookmark-filtervalue-not-normalized`,
  `engage-selector-not-normalized`, `segfilter-no-selected-type-untouched`,
  `segfilter-operand-string-type-untouched`, `segfilter-operand-nan-untouched`).
  `normalize_numeric_string` uses the Python float grammar incl. underscores and
  whitespace — both pinned as selftest cases so TS must mirror. One OBSERVATION (not a
  finding): `canonicalize()` applies rule-4 rewriting to the WHOLE tree it is handed,
  including `expect.result` and error contents, whereas R10.11's server-equivalence
  evidence covers request-side segfilter operands. In practice masked-diff risk is nil:
  the trigger shape is segfilter-only and wire results come from identical canned
  response bytes on both sides; noted for the record.
- **Rule 5** ✓ `_js_form_from_repr_exponent` hand-checked at the window boundaries:
  1e15/1e16/1.5e16/1e20 (plain in JS, exponent in Python repr) → correct JS plain
  forms; 1e21 → `1e+21`; 1e-5/9.9e-5 → `0.00001`-style; 1e-7 → `1e-7` (JS unpadded
  exponent); `-0.0` preserved sign (no `e` in repr → passthrough). All these are pinned
  selftest cases. Python's plain-repr range is a strict subset of JS's plain range in
  both directions, so no reverse-window case exists — the implementation is sound.
- **Rule 6** ✓ `canonicalize_error` strips `message`/`suggestion`/`fix` at exactly two
  levels (top + mapping elements of `errors[]`); NO recursion into `details_contain`
  (selftest `error-details-contain-message-survives`). Both record (`emit._encode_error`)
  and replay (`execute.py` line 378-385) run the SAME `_encode_error`, so
  `details_contain` is effectively full-details-minus-advisory equality — symmetric,
  strictly stronger than subset, no drift possible between recorder and runner.
- **Rules 7-8** ✓ `headers_match`: subset semantics (unlisted actual headers ignored —
  selftest `headers-ignore-unlisted`), lowercased keys both sides, pattern values via
  `re.search`. `re.search` would under-constrain an unanchored pattern, but an
  exhaustive corpus scan found **0 unanchored patterns** (all 10 distinct auth patterns
  are `^...$`, generated by `emit.py:590` `f"^{re.escape(...)}$"`).
- **Rule 9** ✓ group members re-sorted among the group's own positions by the same
  `(method, path, params)` canonical key `emit.py` uses at write time.
- **Rules 10-11** ✓ `$type`-tagged and bytes objects treated as ordinary objects.
- **Selftest**: 57 cases spanning value/error/interactions/headers/reject kinds; every
  D6-mandated case present (float-exponent table, `-0.0`, `18.0`-vs-`18`
  non-unification, `int-beyond-2-53`, segfilter positives AND non-targets, error strip
  levels, null-vs-absent, unlisted-header ignore, lone-surrogate/NaN/±Infinity
  rejects). Re-ran: `uv run pytest conformance/tests/test_canonical_selftest.py` →
  **61 passed**.
- **Request diff is EXACT, not subset**, for the core (`execute.py`
  `_REQUEST_CORE_KEYS`: method/scheme_host/path/params/json_body/body_text/body_base64
  compared as one canonical structure) — so param-absence assertions (vectors 19, 28)
  survive. `headers_contain`/`headers_absent`/`params_absent` diff separately with
  their own semantics.

**§B verdict: no over-normalization found.** The canonicalizer is a faithful D6
implementation; the only latitude beyond the letter of D6 is the rule-4 tree-wide
application noted above (symmetric, segfilter-shape-gated, zero observed effect).

## C. D5 redaction sweep

Independent scanner over ALL committed vector artifacts (2,612 objects: every JSONL
line incl. `$bundle` headers, manifest.json, api-index.json, enums/bookmark_enums.json)
implementing D5.4 + extras: home paths (`/Users/`, `/home/`), `sk-` token prefixes,
AWS `AKIA`, GitHub `ghp_`/`gho_`, Slack `xoxb-`/`xoxp-`, Google `AIza`, PEM blocks,
`Bearer <token>` not in the vector's session-derived allowset, and any
`[A-Za-z0-9+/=_-]{40,}` string not derivable from the bound session.

Results — every hit triaged benign:
- High-entropy hits are all API URL paths (my char class included `/` and `-`), the
  region-probe fake secret `xxxx…`, an authored formula-length test pad `AAAA…`, one
  base64 CSV that decodes to `product_id,name\n1,Widget\n2,Gadget\n`, and the
  manifest's own `source_commit` sha.
- All 10 distinct authorization patterns in the corpus decode to obvious fakes:
  `test_user:test_secret`, `u:s`, `team.sa:team-secret`, `SECRET`, `xxx`, and bearer
  values `test-token`, `test-oauth-token`, `stub-token`, `ci-bearer`, `eu-token`.
- Zero home paths, zero real-shaped credentials, zero `sk-`/vendor-prefixed tokens.

**§C verdict: D5 redaction held.** Nothing in the committed corpus resembles a real
credential or leaks a local path.

## D. Exclusion ledger honesty

`manifest.exclusions` has 11 categories; `exclusion_details` itemizes nodeids for the 6
small ones (the four bulk buckets — cli 506, hypothesis 537, no_seam_hit 2668,
wire_call_no_transport 610 — are counts only). Sampled 3 categories × 2 tests + 1
bonus, reading each source test:

1. **uncoded_raise** (14) —
   `test_query_user_edge_cases.py::TestTier2CrashPaths::test_t2_05_filter_to_selector_unsupported_operator`
   raises bare `ValueError` (catch-all at user_builders.py:142);
   `test_user_builders.py::TestFilterToSelectorBetweenBoundsValidation::test_string_lower_bound_rejected`
   raises bare `ValueError`. Both genuinely uncoded per R5.5 (`_encode_error` returns
   None for non-Mixpanel exceptions). **Reason applies.**
2. **fs_dependent** (4) — both sampled `TestUploadLookupTable` tests
   (`test_async_upload_failure_raises`, `test_orchestrates_upload_and_returns_lookup_table`)
   pass `UploadLookupTableParams(file_path=str(tmp_path/"...csv"))` — a nondeterministic
   pytest temp path in `call.input`, unreplayable in either runner. **Reason applies.**
3. **raw_transport_no_entrypoint** (34, sampled 2) — `TestIterJsonlLines::test_simple_lines`
   and `test_line_without_trailing_newline` drive a bare `httpx.Client` +
   private `_iter_jsonl_lines(response)` directly: transport traffic with no registry
   entry point to attribute. **Reason applies** — and the contract is COMPENSATED by 6
   authored `streaming/api_client._iter_jsonl_lines/*` vectors (blank lines, CRLF,
   no-trailing-newline, gzip chunk boundary, line split across chunks, mid-codepoint
   split), which cover the excluded tests' behaviors and harder cases.
4. **test_local_clock** (1, bonus) — `TestBuildTimeSection::test_from_only_fills_today`
   patches the module-local `date` object (`mock_date.today → 2025-06-15`), which the
   global freeze can't honor; compensated by the authored
   `authored-from-only-today-fill-record-epoch` vector (sampled as #4 in §A) pinning the
   same today-fill contract at the record epoch. **Reason applies, honestly compensated.**

**§D verdict: exclusion ledger honest** in every sampled case; two exclusion families
carry explicit authored compensation.

## Summary

- 40-vector stratified sample (17 capabilities; wire w/ setup ×2, multi-interaction
  ×3+, builder, validation-error ×4, parse ×2, authored ×8): 38 FAITHFUL, 2 WEAKENED
  (F1 pin-precondition loss, F2 redaction-message drop), 0 MISENCODED, 0 real-credential
  issues.
- Independent full-corpus replay: 2609/2609 PASS (1.17 s).
- Canonicalizer: faithful D6 port, no over-normalization, selftest complete (61 pass),
  all auth patterns anchored.
- Redaction: clean corpus-wide.
- Exclusions: honest, with authored compensation where claimed.

Neither finding blocks the Phase-1 gate; both should get either a ledger entry or a
small mechanism (pre-setup session emission; `message_not_contains`) before the corpus
is treated as the sole Layer-1 authority.
