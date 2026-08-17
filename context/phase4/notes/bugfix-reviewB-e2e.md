# Pair-B Review (BLIND) — Lens 2: Adversarial E2E + Server-Shape Correctness

Reviewer: pair-B (blind to reviewA files per orchestrator ruling).
Scope: Python ts-port/python-bugfix-batch (vs ts-port/phase2-contract-support) + TS main (vs 8fa150d).
Bar: 4 fix-of-record docs + inbound-ledger row 2.

## Plan
- [ ] Read fix-of-record docs (a)-(d) + inbound-ledger row 2
- [ ] Diff inventory both repos
- [ ] (a) frequency-filter clause shape vs ../analytics bookmark_parser + bookmark.json schema (READ-ONLY), run referees independently, hand-verify clause
- [ ] (b) dataGroupId string|null at BOTH sites — real builder e2e in BOTH languages, byte-diff emitted JSON
- [ ] (c)/(d) minimal mocked-transport e2e drivers in both languages, diff outcomes
- [ ] Findings

## Log
### Inventory (read, not yet verified)
- Python batch: bddc576 (FIX-1 a+b), 57c5e16 (FIX-2 c+d), a1d43a5 (RE-PIN @700db99), 20c7d6b (ARB-A F1 non-dict guard). TS: 2b72ce1 (twins retired + re-pin), b7152da (ARB-A twin locks).
- (a) new clause: dataset/resourceType people/profileType/search/dataGroupId null/behavior{aggregationOperator,behaviorType $frequency,dateRange,event{label,value},filters,filtersOperator}/filterType number/defaultType number/filterOperator/filterValue/propertyObjectKey/value.
- (b) str coercion at clause sites (buildGroupSection x2, cohort entry x2, frequency entry) + sections-level renamed dataGroupId -> globalDataGroupId=str at 3 workspace sites (insights/funnel/retention), both languages.
- (c) uniform serialize: str as-is, None->"", else json.dumps; TS twin removed pyTruthy/TypeError branch.
- (d) redact access_token/refresh_token/id_token in details.response_data; dict-guard (ARB-A F1); TS isPlainRecord twin.
- NOT read (blind): bugfix-reviewA-resolution.md.

### (a) Frequency-filter clause — VERIFIED server-correct
- Independent referee re-run (my own handoff regen — byte-identical to committed): structural 314/314 ACCEPT; deep 125 ACCEPT / 0 REJECT / 189 SKIP (exit 0 both). The 2 former deep REJECT vectors now ACCEPT.
- Hand-verified bare clause keyset == platform-native fixture (analytics api/version_2_0/insights/test.py test_multi_metric_bar_and_table_chart_csv_exports) EXACTLY, incl. behavior subkeys.
- date_range_validator (validate.py:184 + TIME_VALIDATION_SCHEMA parser.py:205, window=TIME_OFFSET_SCHEMA {unit In VALID_TIME_UNITS, value int}): emitted {"type":"in the last","unit",window:{unit,value}} valid; day/week/month ⊂ VALID_TIME_UNITS, date_range_value int.
- 19 adversarial build_params payloads (lookback day/week, event_filters non-empty/empty, label, mixed, float value, 5 operators, dgid variants) — deep oracle ACCEPT 19/19, structural ACCEPT 19/19, ajv ACCEPT 17/17 (2 non-insights SKIP).

### (b) dataGroupId — clause + sections sites verified
- Clause sites all emit "5" (str): cpref, inline-cp, cohort entry (both dataGroupId and interior data_group_id "5"), frequency entry. Sections sites emit globalDataGroupId:"7"/"9"/"11" (insights/funnel/retention) — no dataGroupId key remains.
- Vendored bookmark.json: Sections additionalProperties:false, has globalDataGroupId $ref DataGroupId (string|null), NO dataGroupId; GroupClause.dataGroupId string|null. Deep validator: dataGroupId Any(None,str) at clause; cohort interior Any(int,str,None).
- ajv referee (npm run referee:bookmark): 9/9 pass; feed test pins RETIRED (all-accept enforced, checked source).
- NOTE: plain-string GroupBy path emits NO dataGroupId key at all (pre-existing shape, unchanged).
- TODO: TS byte-diff, (c)/(d) drivers.

### (b) Cross-language byte-diff — CLEAN
- 21 matched builder e2e calls (public Workspace facade both languages: ff variants x13, dgid clause sites x4 incl. cpref + inline-cp, sections-only, funnel, retention): 21/21 byte-identical after identical canonical re-serialization (key ORDER + values compared; TS payloads produced by JSON.stringify insertion order, parsed order-preserving).
- Driver artifacts: /tmp/reviewB_gen_payloads.py, /tmp/reviewB-ts-driver.ts (esbuild-bundled), outputs /tmp/reviewB-payloads*.jsonl, /tmp/reviewB-ts-payloads.jsonl.

### (c) 403-sniff mocked-transport drivers — CONVERGENT
- 20-case body matrix (scalars truthy/falsy, list exact/substring, nested substring, bigint 29-digit, empty containers, non-JSON, unicode-embedded flag): Python `_handle_response` vs TS `handleResponse` — 20/20 identical (class+code). No TypeError anywhere; uniform substring semantics confirmed (list-substring + nested-substring now SessionReplayAccessError in BOTH).
- Artifacts: /tmp/reviewB_c_python.py, /tmp/reviewB-c-ts.ts, outputs /tmp/reviewB-c-{python,ts}.json.

### (d) OAuth malformed-200 drivers — CONVERGENT, residual leak noted
- 10-case matrix through Python flow.exchange_code (MockTransport) vs TS postTokenRequest (fake fetch): 10/10 identical (class, code, response_data STRING byte-equal incl. pythonStr dict rendering, leak flag).
- Canonical cases redact all three keys; non-dict 200 bodies raise coded OAuthError in both (ARB-A F1 verified e2e).
- RESIDUAL (both languages identically — NOT a divergence): (1) nested token material not redacted ({"data":{"access_token":"SECRET_NEST"},"expires_in":3600} → SECRET_NEST verbatim in details.response_data); (2) bare-string 200 body renders verbatim ("SECRET_BARE_STRING"); (3) non-canonical keys leak (client_secret, Access_Token case-sensitive). Fix-of-record's alternative (drop response_data, keep field names) would have covered these. MINOR hardening finding.
- browser/README.md now says "bearer material no longer flows through it" — overstated vs residuals above. MINOR doc finding.
- New corpus vector locks redacted response_data string exactly (auth/test_auth_flow.jsonl).

### Re-pin + gates
- TS conformance re-run by me: 3,262/3,262 PASS, 0 fail, 0 unported @ 700db99; both manifests pinned 700db996cc95.
- Unaffected vectors spot-checked: stamp-only ($bundle source_commit) changes.
- ajv referee 9/9; pins retired in source (all-accept enforced). Handoff regen byte-identical; both bookmark oracles clean on MY runs.
- Flipped tests STRENGTHENED (full-dict equality + explicit no-customProperty regression test) — no R10.2 weakening seen.
- Touched Python test files re-run: 386 passed.

### Server-side reader analysis (b, sections-level)
- INSIGHTS engine reads sections.globalDataGroupId (api/version_2_0/insights/{params.py:2618, api.py:553, bookmark.py:287}); server test fixtures place it in sections as str. Correct spelling+placement+type.
- FUNNELS/RETENTION engines: NO reader of either sections-level spelling found (old sections.dataGroupId equally inert). Rename is contract-aligning, behavior-neutral; modern-funnels oracle gap already tracked (L5-F2/R6). Observation only.

### Verdict
No blockers. No cross-language divergence found in any driver. Schema/server-shape checks all pass. 2 minor findings (d-residual redaction depth; README overstatement).
