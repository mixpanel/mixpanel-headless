# B0 Adversarial Review — Lens: Assertion Fidelity + Rulebook Compliance

**Reviewer**: B0 review pair, assertions lens · fable · 2026-08-15
**Scope**: B0-1 + B0-2 commits — Python repo `b5c1369..748ab45` (since playbook 6bd88b5),
TS repo `b67ce85..613c8e6` (since pre-B0 HEAD d5dd02c).
**Status**: COMPLETE. Verdict: **GO with 2 minor findings + 3 observations** — zero
weakened assertions found; every rulebook check in this lens passes.

## Checklist (per task packet)

- [x] R10.2 assertion-for-assertion diff of every translated test vs Python original — PASS
      (0 weakened/dropped without documentation; details below)
- [x] R2.10 no bare catch on transport paths (both `except httpx.HTTPError` ports are
      `instanceof MixpanelHttpError`-guarded: internals.ts:685, app-request.ts:260) — PASS
      (see Finding 2 for the separate JSONDecodeError-analog catches)
- [x] R2.11 redirect manual + throwing raise_for_status helper — PASS (internals.ts:347-357
      helper throws `MixpanelHttpError` with status; wrapped with `cause` at the
      HTTP_ERROR sites; `redirect:'manual'` is contract-documented on `RequestExecutor`
      (internals.ts:106-115) — the concrete fetch adapter is B4-C1 by design; 302 test
      internals.test.ts:549 locks 3xx→HTTP_ERROR-never-success)
- [x] R2.12 *Seconds vs *Ms naming — PASS (`timeoutSeconds`, `retryWaitSeconds`,
      `BACKOFF_*_SECONDS`; `sleep(ms)` with the ONE `waitSeconds * 1000` conversion at
      internals.ts:671 / app-request.ts:216; `retryAfter` seconds-under-Python-name is the
      playbook-blessed exception)
- [x] R4.8 lookup tables as ReadonlyMap — PASS (`ENDPOINTS: ReadonlyMap<Region,
      ReadonlyMap<EndpointKind,string>>` url.ts:31; `DIGIT_VALUES: ReadonlyMap`
      numeric-parse.ts:24; whitespace tables `ReadonlySet`; results-unwrap membership via
      `Object.hasOwn` app-request.ts:253)
- [x] R6.7 AbortSignal — N/A-at-B0 per playbook (four points are B4 scope); see
      Observation C for the seam hand-off note
- [x] R9.1 core purity — PASS (`grep -rn "node:" packages/core/src` → zero imports,
      prose mentions only; env reads injected via `getCustomHeaderEnv` provider,
      headers.ts:97-111)
- [x] R5 error classes preserve names + codes — PASS (errors.ts diff is type-widening of
      `responseBody` to `unknown` only; `MixpanelHttpError` deliberately OUTSIDE the
      hierarchy = httpx.HTTPError parity; new coded errors PY_INT_INVALID_LITERAL /
      PY_INT_UNSAFE_INTEGER / PY_FLOAT_INVALID_LITERAL asserted BY CODE everywhere)
- [x] GATE-VERDICT R5 grep — PASS (`grep -rn "JSON.parse\|.json()" packages/*/src`: only
      lossless-json.ts:233 escape-decoding on a validated string token inside
      parseLossless itself, plus doc comments; wirestub.ts:198 is the grandfathered rig
      exception; rig lossless-json.ts is now a re-export shim FROM core — GF5 direction
      correct, library never imports the rig)
- [x] Binding honesty (P3-5 rule 3) — PASS (bindings.ts:356-394 calls the REAL
      `iterJsonlLines` imported from `packages/core/src/client/jsonl.js`; the binding adds
      only chunk-stream rebuild + gzip transport decompression, mirroring
      `conformance/record/adapters.py:81-113` which calls the real `_iter_jsonl_lines`;
      the six compat.* bindings call the real `pythonInt`/`pythonFloat`/`pythonStrip`/
      `sortedByCodepoint`/`cpLength`/`cpSlice`, with the pythonFloat non-finite sentinel
      encoding mirroring the Python reference wrapper `pycompat_ref.python_float`
      verbatim — the transform is recorder-contract, not binding-invented)
- [x] Authored compat vectors assert codes/values, not messages (R5.4) — PASS (all 12
      error vectors in pythoncompat-b0.jsonl carry ONLY
      `{"class":"MixpanelHeadlessError","code":"PY_*"}`; the 60 output vectors assert
      values; zero message asserts)

## Findings

### Finding 1 (minor, R10.2 audit trail) — jsonl.test.ts header misstates its Python source

`packages/core/test/client/jsonl.test.ts:4-7` claims "Python has no direct Layer-3 unit
suite for `_iter_jsonl_lines`". FALSE: `tests/unit/test_api_client.py::TestIterJsonlLines`
(:2709-2877) is exactly that — 8 unit tests driving `_iter_jsonl_lines` directly. I
diffed all 8 against the TS suite: every behavior IS covered (simple lines → "handles
many lines within one chunk"; no-trailing-newline / blank-lines-skipped / chunk-boundary /
mid-codepoint-split / empty-response / whitespace-only-skipped → the authored-* and named
cases; utf8_content is subsumed by the strictly-harder split-😀 case), so **no assertion
was lost** — but the header breaks the 1:1 name mapping and citation discipline R10.2
leans on (phase2-audit A2 style), and a later auditor diffing "translated tests vs Python
originals" from headers alone would wrongly conclude TestIterJsonlLines was never
translated. Fix: correct the header to cite TestIterJsonlLines :2709-2877 as a source
alongside the authored vectors.

### Finding 2 (minor, fidelity edge) — JSONDecodeError-analog catches are bare, unlike the in-repo ValueError-analog pattern

Python catches `json.JSONDecodeError` SPECIFICALLY at the body-parse sites; the TS ports
use bare `catch`:
- `internals.ts:328` (`parseBody`), `internals.ts:532` (`_handle_response` tail reparse),
  `app-request.ts:225` (422 body parse).

`backoff.ts:132` shows the correct in-repo pattern for a Python-builtin-exception port:
`if (cause instanceof MixpanelHeadlessError) return null; throw cause;`. A
`LosslessJsonError` instanceof-guard is the analog here. Failure scenario (pathological
but real): a deeply-nested JSON body overflows the recursive-descent parser with a
`RangeError` — Python's equivalent (`RecursionError` from `json.loads`) is NOT caught by
`except json.JSONDecodeError` and propagates, while the TS bare catch swallows it into
the text-truncation / INVALID_RESPONSE path. Not an R2.10 violation (that rule scopes
`httpx.HTTPError` ports, both of which are correctly guarded) — filed as a fidelity nit
for the arbiter; one-line fix per site.

## Observations (no action required to pass the gate)

- **A. cp_length authored budget ambiguity**: packet B0-1 item 3 reads "Authored vectors
  `compat.cp_slice`/`compat.cp_length` (≥10: …)". Delivered: cp_slice 11, cp_length 5
  (combined 16). Compliant under the combined-bullet reading (the listed cases are
  slice-shaped); short 5/10 if read per-api. All named case families (non-BMP cut point,
  negative indices, start>end, empty) are present. Arbiter to bless the reading.
- **B. jsonl.ts:40 JSDoc example uses `JSON.parse(line)`** — a faithful translation of the
  Python docstring's `json.loads`, and not a GATE-R5 violation (doc text, not code), but
  B4-C2's streaming port must parse lines via `parseLossless`; consider a caveat in the
  example so the B4 shard isn't steered wrong.
- **C. R6.7 hand-off**: B0's `RequestExecutor`/`sleep` seams carry no `AbortSignal`
  parameter. The four R6.7 points are B4 scope, and B4-C1 can satisfy them without
  touching B0 signatures (inject signal-aware `request`/`sleep` closures; an AbortError
  rejection passes the `instanceof MixpanelHttpError` filter unwrapped, which is the
  desired propagation). B4-C1's packet should state this explicitly.
- **D. B4 hand-off list is load-bearing**: packet FF4 says the streaming-site
  `project_id` (raise `:1883-1891`, Layer-3 lock `test_api_client.py:1567`) is locked
  ONLY by faithful translation of that test — it is deferred to B4-C2 via B0-notes
  deviation 3. The B4 gate must verify TestRetryStateResetRegression (4 tests) +
  test_export_events_negative_retry_after_uses_backoff + the form-encoding content-type
  assert + auth-header wire captures actually land.
- **E. Sanctioned divergences confirmed as documented**: (i) Retry-After > 2^53−1 →
  `PY_INT_UNSAFE_INTEGER` inside pythonInt → header reads as absent (backoff.ts:117-120,
  B0-notes decision 7, blessed by the playbook packet text); observable delta is
  `RateLimitError.retry_after` null-vs-huge-int in the >2^53 corner only. (ii) TextDecoder
  BOM-eat divergence was FOUND by the R10.9 fuzz and fixed (`ignoreBOM: true`,
  jsonl.ts:56) with a locking unit test — the repro workflow ran as designed.

## R10.2 assertion-for-assertion diff (per translated file)

Every ✓ below = each Python assertion located in the TS twin at equal or greater
strength; "strengthened" = TS adds asserts on top (allowed; never the reverse).

| TS file | Python source (read live) | Verdict |
|---|---|---|
| `test/client/internals.test.ts` | TestRateLimiting :441-549 (5/5 tests; sleepsMs + FF4 reduced-shape asserts ADDED), TestErrorHandling :1258-1311 (3/3 incl. 412 responseBody equality), TestServerErrors :1314-1362 (3/3), TestPublicRequest B0-observable subset :1660-1795 (9 tests; URL/auth plumbing asserts correctly deferred to B4-C1 per header), TestRetryAfterHardening execute half :3629-3761 (5/5; monkeypatched 0.125s backoff → deterministic zero-jitter 1s→1000ms, assertion CONTENT preserved: header rejected, fallback path reaches sleep), TestBlankErrorBodyFallbacks :3859-3987 (8/8 exact message-default equality incl. " boom " no-strip), TestErrorContextSymmetry::test_401_carries_request_body :3998-4025 (3/3 asserts), sign_replays TestSensitiveDataMapping/TestOtherHttpErrors + R10.7 list/scalar/falsy branches | ✓ strengthened |
| `test/client/app-request.test.ts` | TestAppRequest :78-303 (16/16; + raw:true and no-query_origin locks ADDED), TestAppRequestFormBody :306-403 (4/4; content-type wire assert → B4 adapter, documented header), TestCodedAppRequestCodes :873-929 (2/3; `test_ac1_stays_catchable_as_value_error` documented-excluded in header — Python dual inheritance untranslatable, class+code asserts preserved), TestRetryAfterHardening app half :3763-3808 (2/2), TestErrorContextSymmetry app half :4027-4116 (3/3), settings-headers re-check at appRequest level (2/2) | ✓ |
| `test/client/backoff.test.ts` | TestParseRetryAfter :3499-3551 (5/5 with IDENTICAL parametrize lists incl. HTTP-date + "1e3"/"0x10"/"nan"), TestRetryWaitSeconds :3554-3592 (5/5 incl. 2**40 cap case; pytest.approx → exact equality under injected RNG, strictly stronger) + formula locks ADDED | ✓ strengthened |
| `test/client/url.test.ts` | TestEndpoints :83-116 (4/4), TestBuildUrl :281-325 (6/6, every literal URL byte-identical to ENDPOINTS source) | ✓ |
| `test/client/headers.test.ts` | test_settings_headers.py::TestSessionHeadersOnOutboundRequests :156-236 (2/2; env monkeypatch → injected provider, documented) + layer-order/UA/metadata locks ADDED; B8-owned classes of that file correctly NOT translated (playbook B0 row) | ✓ strengthened |
| `test/client/scope.test.ts` | TestWorkspaceScoping maybe_scoped_path half :414-443 (3/3), TestAppApiEdgeCases :759-784 (2/2 incl. workspace-id-0); require_scoped_path/resolve_workspace_id correctly deferred B4-C1 (network discovery, playbook table note) | ✓ |
| `test/client/jsonl.test.ts` | TestIterJsonlLines :2709-2877 — all 8 behaviors covered; header citation WRONG (Finding 1) | ✓ behaviors / ✗ citation |
| `test/client/lossless-json.test.ts` | moved with the parser (7-line import-path diff only) | ✓ |
| compat test files (B0-1) | no Python originals (CPython is the oracle; R10.1 new tests); codes asserted via `.code`, never message text | ✓ |

Deferred-to-B4 list cross-checked against B0-notes deviation 3 (TestRetryStateResetRegression ×4, test_stream_rate_limit_error_carries_project_id, test_export_events_negative_retry_after_uses_backoff, form content-type, auth-header wire captures, test_request_lexicon_schemas_example URL plumbing) — every deferral has an owner and its raise/plumbing site genuinely lives in B4 code. Zero undocumented drops.

## Verification runs (this review, 2026-08-15)

- `npx vitest run packages/core/test/client packages/core/test/compat` → 15 files,
  **300/300 passed**.
- `npm run conformance` → **3,251 vectors — 539 PASS / 0 FAIL / 2,712 UNPORTED @
  b5c1369** (matches the B0-2 commit claim exactly: 533 + 6 jsonl-chunk vectors).
- `node throwaway/b0-2/run-edge-harness.mjs` → **47 passed, 0 failed** (reproduces the
  RUN record's deterministic edge-set count).
- `uv run python -m pytest conformance/tests/test_pycompat_ref_b0.py
  conformance/tests/test_registry.py -q` → **118 passed**.
- CPython live probes (uv, 3.14): `int("\x1c42")` ValueError / `int("\x0b42")`=42 /
  `int("42")`=42 / `int("﻿42")` ValueError / `"\x1c42\x1f".strip()`="42" /
  `int("٤٢")`=42 / `int("1_0")`=10 / `int("9007199254740993")` OK-in-CPython — confirms
  the generated whitespace/digit tables encode the isspace-vs-numeric trap correctly and
  the 2^53 rejection is a TS-side sanctioned deviation, exactly as documented.

## Evidence log

### Source-fidelity pass (B0-2 src modules vs api_client.py, read live 2026-08-15)

- `internals.ts:294-315` `errorMessage` vs `api_client.py:81-106`: `{"error": null}` ==
  absent (both -> default); non-string error -> `pythonStr`; `body[:200]` -> `cpSlice`;
  `.strip()` check -> `pythonStrip` but returns UNSTRIPPED text — matches Python
  (`return text if text.strip() else default`). MATCH.
- `internals.ts:391-541` `handleResponse` vs `:503-662`: branch order 401 -> 403
  (flag scan w/ jsonDumpsLike for dicts, `body or ""` falsy fallback via pyTruthy,
  list membership + truthy-scalar TypeError R10.7 reproduced) -> 400 -> 404 -> other
  4xx -> 5xx -> raise_for_status FIRST -> dict/list return -> re-parse scalar return ->
  INVALID_RESPONSE with cause. MATCH (parseLossless substituted for response.json per
  GATE-R5, sanctioned).
- `internals.ts:611-711` `executeWithRetry` vs `:706-820`: `json_data or form_data`
  dict-TRUTHINESS reproduced (empty jsonData falls to formData); caller params dict
  mutated with query_origin; `timeout or self._timeout` zero-falls-back reproduced;
  429-exhausted RateLimitError shape (retry_after/status/body/method/url/params/
  project_id, NO request_body) matches `:771-780`; fallthrough reduced shape matches
  `:814-820`; loop bound `attempt <= maxRetries` == `range(max_retries + 1)`. MATCH.
- `backoff.ts` vs `:664-704`, `:1159-1185`: jitter on fallback only (`random() *
  delay*0.1` == `uniform(0, delay*0.1)`); header path `min(float(retry_after), 60)` no
  jitter; `_parse_retry_after` int()->pythonInt with coded-error catch as the
  ValueError analog, `parsed >= 0` gate. MATCH (2^53 divergence documented in-code +
  B0-notes decision 7).
- `url.ts` vs `:151-172`, `_build_url:417-432`: table values byte-identical (12 URLs
  diffed by eye against source); string concat only; leading-`/` normalization. MATCH.
- `scope.ts` vs `maybe_scoped_path:1637-1664`: `is not None` guard (workspace id 0
  valid) preserved via `!== null`. MATCH.
- `jsonl.ts` vs `_iter_jsonl_lines:109-148`: byte-buffer, split 0x0A, decode
  utf-8-replace (TextDecoder non-fatal + ignoreBOM:true — BOM-preservation divergence
  found by fuzz and fixed), pythonStrip, skip empty, tail flush. MATCH.
- `headers.ts` vs `_request_headers:452-481` + `client_metadata.py`: 4-layer merge
  order and `if custom_name and custom_value` string-truthiness reproduced; env read
  injected per R9.1 (per-call provider mirrors per-request `os.environ.get`).
  QUERY_ORIGIN byte-identical. MATCH.
- `app-request.ts` vs `app_request:1191-1387`: AC1 guard; auth header resolved once
  per CALL outside the retry loop (matches Python `:1263`); 204 checked BEFORE 429
  (source order); 422 own branch w/ "Unprocessable entity" default; results unwrap
  `Object.hasOwn` w/ `raw` flag; `form_body if not None else json_body` identity (not
  truthiness) reproduced; RateLimitError shapes match `:1314-1323`/`:1381-1387`. MATCH.

### Mechanical grep checks

- R9.1: `grep -rn "node:" packages/core/src/` — zero real imports (only JSDoc prose
  mentions in secret.ts/replays.ts/account.ts). PASS.
- GATE-R5: `grep -rn "JSON.parse\|.json()" packages/*/src` — hits only:
  `lossless-json.ts:233` (escape decoding on a validated string token INSIDE
  parseLossless — pre-existing, moved file), `jsonl.ts:40` (JSDoc @example only),
  doc comments. `wirestub.ts:198` is the grandfathered rig exception per playbook.
  PASS (one doc nit — see findings).
- Binding honesty (P3-5 rule 3): `bindings.ts:356-394` calls the REAL `iterJsonlLines`
  imported from `packages/core/src/client/jsonl.js`; binding adds only stream shape +
  gzip transport decompression, mirroring `conformance/record/adapters.py:81-113`
  which calls the real `_iter_jsonl_lines`. Both sides honest. PASS.
