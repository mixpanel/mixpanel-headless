# ARB-B — Pair B arbiter resolution (security + e2e blind reviews)

Date: 2026-08-17. Arbiter for review pair B of the R10.7 four-bug Python-first
maintenance batch. Inputs: `bugfix-reviewB-security.md` (2 major F-B1/F-B2,
2 minor F-B3/F-B4), `bugfix-reviewB-e2e.md` (3 minor, labelled E-1..E-3 here).
Every claim re-verified independently at source level before action; all fixes
applied red-first with the TS twin flipped in the same change (R10.7 — no
two-behavior window), stable error codes untouched (R5.4), no assertion
weakening (R10.2 — every flipped assertion is strictly stronger: verbatim
renders became secret-absence + placeholder/allowlist locks).

## Verdict table

| ID | Reviewer | Severity | Claim (short) | Verdict | Action |
|----|----------|----------|---------------|---------|--------|
| F-B1 | security | major | non-JSON 200 token body embedded verbatim in `details["response_body"]` (both languages) | CONFIRMED | APPLIED (red-first, both repos) |
| F-B2 | security | major | redaction shallow — top-level exact-lowercase canonical keys only; nested/envelope secrets leak via `response_data` | CONFIRMED | APPLIED (red-first, both repos — allowlist redaction, closes E-1 too) |
| F-B3 | security | minor | non-dict 200 body rendered verbatim (`str(body)`) and test-locked in both languages | CONFIRMED | APPLIED (placeholder; 4 locking assertions flipped in the same change, both repos) |
| F-B4 | security | minor | browser README + Security docstring/JSDoc overclaim; B9 FB-3 scrub guidance retired early | CONFIRMED | APPLIED (docs re-written to match the now-closed channels; scrub-before-telemetry restored as standing advice) |
| E-1 | e2e | minor | same residual channels + non-canonical keys (`client_secret`, `Access_Token` case games) leak — no parity divergence | CONFIRMED | APPLIED (subsumed by the F-B2 allowlist fix; probe shapes locked as tests in both languages) |
| E-2 | e2e | minor | browser README "bearer material no longer flows through it" overstated | CONFIRMED | APPLIED (same README rewrite as F-B4) |
| E-3 | e2e | minor | funnel/retention `sections.globalDataGroupId` engine-inert per analytics source (neutral rename; unverified-live) | CONFIRMED | NO CODE CHANGE (correct per reviewer's own suggestion); recorded below + HUMAN-CALL extending the ARB-A F2 burn-in item |

## Independent verification (not taken from the reviewers' notes)

- F-B1: `flow.py` non-JSON-200 branch raised
  `details={"response_body": response.text}` where `response.text` is a 200
  token-endpoint body; `oauth-http.ts` identical (`{ response_body:
  response.text }`). Red runs (below) reproduced the leak in BOTH languages
  with truncated (`{"access_token": "SECRET_TRUNC", "refr`) and
  garbage-suffixed (`{"access_token":"SECRET_GARB"}garbage`) 200 bodies —
  secret present in `str(exc)+details+to_dict()` / message+`JSON.stringify`.
- F-B2/E-1: the FIX-2 comprehension tested `k in _TOKEN_BEARING_KEYS` on
  TOP-LEVEL keys only (flow.py) / `TOKEN_BEARING_KEYS.has(k)` (oauth-http.ts).
  Red runs reproduced all four probe shapes in both languages:
  `{"result": {"access_token": "SECRET_NEST"}}`, `{"tokens": ["SECRET_L1"]}`,
  `{"client_secret": "SECRET_CS"}`, `{"Access_Token": "SECRET_UPPER"}`.
- F-B3: `else data` branch rendered `str(data)` / `pythonStr(data)` verbatim;
  locked at `test_auth_flow.py` (ex-)`:640`/`:674` and TS
  `oauth-flow-refresh.test.ts` (ex-)`:267` + `oauth-flow-login.test.ts`
  it.each. A bare-string 200 body IS the credential in the
  IdP-returns-naked-token case.
- F-B4/E-2: `packages/browser/README.md` (post-2b72ce1) said "bearer material
  no longer flows through it" and downgraded the B9 FB-3 scrub advice; the
  flow.py/oauth-http.ts Security notes claimed "keeps only field names and
  non-secret values" — falsified by the confirmed channels above while open.
- E-3: READ-ONLY greps of the analytics checkout re-run by the arbiter:
  `globalDataGroupId` has ZERO readers under `api/version_2_0/arb_funnels/`
  and `api/version_2_0/retention/` (only reader: insights —
  `api/version_2_0/insights/params.py:2618`); retention's only dataGroupId
  read is CLAUSE-level (`retention/bookmark.py:126`,
  `group_by.update({"dataGroupId": prop.get("data_group_id")})` — the string
  clause site the batch fixed). The old `sections.dataGroupId` spelling was
  equally unread there, so the rename is behavior-neutral for funnels /
  retention: contract-aligned but only proven live for insights.

## Applied fix (one change per repo, Python-first)

Design constraint honored: the ONE-re-pin batch ruling. The fix was shaped so
NO conformance vector flips — verified by full corpus replays in both
languages (3,262/3,262, pin stays 700db996). The single vector that pins
`response_data` (auth/oauth_flow.refresh_tokens/...-
test_refresh_missing_fields_error_redacts_token_material, payload =
`{access_token, refresh_token, id_token}`) renders byte-identically under the
new allowlist (all three keys unsafe → `<redacted>`, insertion order kept).
No vector covers the non-JSON-200 or non-dict-200 edges (checked: zero 200
interactions with `body_text` in the auth corpus; ARB-A had established the
non-dict edge is in the `raw_transport_no_entrypoint` exclusion bucket).

Mechanism (identical twins):

- `_redact_token_payload(data)` (flow.py) / `redactTokenPayload(data)`
  (oauth-http.ts): allowlist instead of deny-list. Every field NAME stays;
  only values of `_SAFE_TOKEN_DETAIL_KEYS` = {`token_type`, `expires_in`,
  `scope`, `error`, `error_description`} survive, and only when primitive
  (str/int/float/bool/None ⇔ string/number/bigint/boolean/null); everything
  else — any key, any nesting, any container — renders `"<redacted>"`.
  Closes F-B2 and ALL E-1 shapes (nested envelope, list value, bare secret
  under unknown key, `client_secret`, case-variant keys) because unknown-key
  VALUES never render at all.
- Non-object 200 JSON body → fixed `"<redacted non-object body>"` placeholder
  (F-B3), replacing the ARB-A F1 verbatim rendering; the coded-OAuthError
  guard behavior is unchanged.
- Non-JSON 200 body → never embedded (F-B1): `details` now carries only
  `content_type` + `body_length` (code points; TS uses
  `Array.from(text).length` to match Python `len(str)` for byte-identical
  future vectors). Message unchanged (already content-type-only).
- Non-200 branches intentionally untouched: they embed IdP ERROR documents
  (`{"error": "invalid_grant"}`, 5xx text), are vector-locked
  (`OAUTH_REFRESH_REVOKED` / 503 vectors pin `response_body`), and were
  note-only in both reviews. Docs now state this explicitly instead of
  overclaiming.
- Docs (F-B4/E-2): flow.py Security docstring + oauth-http.ts Security JSDoc
  rewritten to describe the three 200-branch behaviors + the non-200 caveat;
  `packages/browser/README.md` bullet rewritten — the FB-3
  scrub-`error.details`-before-telemetry advice is RESTORED as standing
  guidance (non-200 `response_body` is IdP-controlled content) and the
  "bearer material no longer flows" sentence is gone.

## Red-run records

Python (`tests/unit/test_auth_flow.py::TestTokenPayloadRedaction`), pre-fix:
13 failed / 4 passed — e.g. `test_exchange_non_json_200_body_not_embedded`
failed with `SECRET_TRUNC` present in serialized details;
`test_nested_and_non_canonical_token_material_redacted[nested-envelope]`
failed with `SECRET_NEST` in `response_data`;
`test_refresh_non_dict_200_body_raises_oauth_error` failed
`'[1, 2]' == '<redacted non-object body>'`. Post-fix: 56/56 in the file.

TS (`packages/node/test/oauth-flow-{login,refresh}.test.ts`), pre-fix with the
mirrored tests: 13 failed / 43 passed — same shapes, e.g. the refresh
non-JSON member showed `{"response_body":"{\"access_token\":\"SECRET_GARB\"}garbage"}`
in details. Post-fix: 56/56 across both files. The 13/13 symmetry is itself a
parity check (identical channels, identical closure).

New/flipped tests (twinned member-for-member across languages):
`test_safe_fields_stay_visible` (renamed+flipped from
`test_non_secret_fields_stay_visible` — unknown-key value now redacted),
`test_nested_and_non_canonical_token_material_redacted` (4 params),
`test_safe_primitive_values_byte_exact` (locks `str()` ≡ `pythonStr` on kept
int/str values: `"{'expires_in': 3600, 'token_type': 'Bearer', 'scope':
'projects'}"`), `test_safe_key_with_container_value_redacted`,
`test_exchange_non_json_200_body_not_embedded`,
`test_refresh_non_json_200_body_not_embedded`,
`test_exchange_non_dict_200_body_raises_oauth_error` (flipped to placeholder +
`SECRET_BARE_STRING` absence; str param now carries the secret),
`test_refresh_non_dict_200_body_raises_oauth_error` (flipped to placeholder).

## E-3 record (Phase-4 burn-in ledger note)

`build_funnel_params` / `build_retention_params` emit
`sections.globalDataGroupId` (string) per the vendored contract, but no
funnels/retention engine reader of ANY sections-level dataGroupId spelling
exists in the analytics source — the key is engine-inert for those two query
types (as the old spelling also was: no regression, no live behavior change).
It is proven live only for insights (`insights/params.py:2618`).

HUMAN-CALL (extends the ARB-A F2 burn-in item): the Phase-4 live burn-in
probe for the dataGroupId spelling should ALSO cover one funnel and one
retention bookmark save — confirm the App API round-trips
`sections.globalDataGroupId` for those report types (or documents that the
server strips it), closing the "contract-aligned but unverified-live" gap.
No batch change: modern-funnels oracle coverage remains the tracked L5-F2/R6
gap.

## Ripple checks (pair-A-verified checks my fixes touch, re-run)

- Python conformance replay over the pinned corpus: 3,262/3,262 PASS
  post-fix — zero vector flips, pin stays 700db996, NO second re-pin event
  (the batch ruling holds).
- TS full-corpus conformance: re-run post-fix — result in the gate section.
- ajv bookmark referee: re-run (untouched surface, cheap insurance) —
  result in the gate section.
- ARB-A F1 members: the flipped non-dict tests still lock the coded
  OAuthError + record-guard behavior ARB-A applied (only the RENDERING
  changed, verbatim → placeholder); ARB-A's crash-regression protection is
  intact and strictly stronger.
- Auth-subsystem LoC budget (`tests/unit/test_loc_budget.py`): the flow.py
  hardening (+helper, +constants, +mandatory docstrings) tripped the 8900
  cap at 8912. Handled per the guard's own protocol (justify or refactor):
  cap bumped 8900 → 8975 with a dated justification entry naming this
  resolution — not an R10.2 concern (repo hygiene guard with an explicit
  bump protocol, not a ported behavior assertion).
- Full gates both repos (results in the gate section below).

## Gate results (all green)

- Python: `env -u FORCE_COLOR -u COLORTERM just check` EXIT=0 (lint,
  fmt-check, typecheck, docstring-cov, test-cov, conformance, build). First
  attempt failed ONLY the auth LoC budget guard (8912 > 8900) — bumped to
  8975 with a dated justification (see ripple section); re-run fully green.
  `tests/unit/test_auth_flow.py` 56/56.
- Python conformance replay: 3,262/3,262 PASS, zero vector flips, pin
  700db996 held (inside `just check` and verified standalone pre-commit).
- TS: `npm run check` EXIT=0 (typecheck, lint, fmt:check, 9,988 tests across
  243 files incl. the 13 new/flipped members, smoke:browser).
- TS full-corpus conformance: 3,262/3,262 passed, 0 failed, 0 unported
  @ 700db996cc95 (unchanged pin — no vector flips, NO second re-pin event).
- ajv bookmark referee: `npm run referee:bookmark` 9/9 green, 0 REJECT
  (ripple insurance re-run; surface untouched by this fix).

## Two-pair convergence note (A ∩ B)

- Same ground, opposite depths: pair A's fidelity review caught the CRASH on
  the non-dict-200 edge (ARB-A F1, guard applied); pair B's security/e2e
  reviews caught the LEAK CLASS in the surviving redaction (F-B1/F-B2/F-B3).
  ARB-B's fix strictly contains ARB-A's: the record guard remains (coded
  OAuthError on non-object bodies, both languages), while the rendering it
  locked was hardened from verbatim to placeholder — flipped in the same
  change on both sides, so the ARB-A convergence locks were strengthened,
  not weakened.
- Both pairs independently confirmed the two batch invariants: (1) corpus
  3,262/3,262 @ 700db996 in both languages with the four twins retired and
  referees clean; (2) the dataGroupId `globalDataGroupId:string` spelling
  rests on static oracles only. Pair A flagged it live-unverified
  (ARB-A F2 HUMAN-CALL); pair B's e2e sharpened WHERE it matters: the
  spelling is engine-read only by insights — funnel/retention emission is
  engine-inert either way. The two HUMAN-CALLs merge into one burn-in probe
  (bookmark save per report type, § E-3 above).
- Both pairs' verdicts on fixes (a)/(b)/(c) agree with no surviving
  findings: pair B's e2e independently re-derived the frequency-clause
  server shape, byte-diffed 21 builder payloads Python-vs-TS, and fuzzed the
  403 sniff 20-way with zero divergence — nothing for the arbiter to apply
  beyond fix (d) hardening and the E-3 ledger record.
- Net batch state after both arbiters: four bugs fixed + one crash
  regression (A) + one leak class (B) closed, all Python-first with same
  change twin flips; ONE re-pin event total; pin 700db996 held through both
  arbiter passes.

## Commits

- TS (`main`): da68958 — allowlist redaction + non-JSON/non-object 200
  handling in oauth-http.ts, 13 mirrored red-first test members, browser
  README + JSDoc rewrite.
- Python (`ts-port/python-bugfix-batch`): the ARB-B commit containing the
  flow.py hardening, the red-first tests, the LoC-budget bump, and this
  notes file (hash in the arbiter's final report — this file is part of
  that commit).
