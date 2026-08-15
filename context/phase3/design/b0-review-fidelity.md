# B0 Adversarial Review — SEMANTIC FIDELITY lens

**Reviewer**: fidelity lens (adversarial pair, playbook P3-2 step d)
**Date**: 2026-08-15
**Scope reviewed**: Python repo `ts-port/phase2-contract-support` commits `b5c1369..748ab45`
(5 commits since `6bd88b5`); TS repo `main` commits `b67ce85..613c8e6` (5 commits since
`d5dd02c`). Verified against the ACTUAL Python source at the current support-branch HEAD
(post-PR-206) — task summaries not trusted; every cited range re-read.
**Verdict**: GO with findings — 1 major (latent, not vector-observable), 2 minor.
No blocker. No unsanctioned R10.7 "improvement" found; the two deliberate deviations
found are documented in `B0-notes.md` (decisions 7 and 8) with one packet-justification
error noted below.

---

## 1. What was verified (evidence per item)

### 1.1 Branch-by-branch diff vs pinned Python source (all read this session)

- **`_handle_response` (`api_client.py:503-662` vs `client/internals.ts:391-541`)** —
  branch order identical: 401 → 403(flag → plain) → 400 → 404 → other-4xx → 5xx →
  `raise_for_status` → dict/list return → scalar re-parse → INVALID_RESPONSE. Every raise
  site carries the full context bag (`status_code`/`response_body`/`request_method`/
  `request_url`/`request_params`/`request_body`). Defaults verbatim: "Permission denied",
  "Unknown error", "Resource not found", "Request failed", `"Server error: " + str(status)`.
  403 flag branch: `json.dumps`-equivalent serialization for dict bodies (`jsonDumpsLike`,
  separator/ensure_ascii differences provably cannot create/destroy the all-ASCII flag
  substring), `(body or "")` Python truthiness (incl. zero-valued JsonNumber), LIST bodies
  use element-equality membership, truthy non-container scalars raise TypeError — the
  R10.7 bug-compat mandated by B0-notes decision 5, locked by internals.test.ts + edge
  harness cases 403-truthy-scalar/403-list-exact/403-list-substring.
  `details.project_id = pythonInt(session.project.id)` as int (internals.test.ts:474
  asserts the NUMBER 12345). Fallthrough tail in exact source order per
  review-resolution R6: raiseForStatus FIRST (any non-2xx incl. 3xx → MixpanelHttpError →
  wrapped as HTTP_ERROR by the retry-loop catch, matching httpx raise_for_status which
  raises for every non-success status), then object/array return, then the scalar
  re-parse (httpx `Response(200, b"42").json()` → 42 confirmed in the packet; TS returns
  the JsonNumber token).
- **`_error_message` (`:81-106` vs `errorMessage`, internals.ts:294-315)** — dict path:
  `error` absent OR null → default (review-resolution R11, never the string "None");
  string error as-is; non-string → `pythonStr` rendering; string body → `cpSlice(...,0,200)`
  codepoint truncation; blank-after-`pythonStrip` → default. Order of truncate-then-strip
  matches. Non-dict/non-str bodies (list, scalar, JsonNumber) → default, matching Python's
  isinstance chain.
- **backoff trio (`:664-704`, `:1159-1185` vs `client/backoff.ts`)** —
  `min(1.0 * 2^attempt, 60.0) + uniform(0, delay*0.1)`; jitter ONLY on the fallback path,
  via injectable `RandomSource` (`random.uniform(0, x)` ≡ `random() * x` — faithful, since
  CPython `uniform(a,b) = a + (b-a)*random()`). Header path: `min(retryAfter, 60)` with NO
  jitter. `parseRetryAfter`: full CPython `int()` grammar via `pythonInt`; unparseable →
  null; negative → null; HTTP-date → null. Post-PR-206 raw-value-reported behavior locked:
  internals.test.ts:384 asserts `retryAfter === 3600` reported while the sleep capped at 60.
  Hostile-header parametrize lists translated verbatim from `test_api_client.py:3518-3551`
  ("abc","5.5","","Wed, 21 Oct 2015 07:28:00 GMT","1e3","0x10","nan"; "-1","-3600") plus
  the caps (61/3600/86400/2^40) — 2^40 < 2^53 so pythonInt handles it.
- **`_execute_with_retry` (`:706-820` vs `executeWithRetry`)** —
  `request_body = json_data or form_data` dict-TRUTHINESS (empty json_data falls through);
  caller-dict `params` mutation + `query_origin` injection reproduced (B0-notes decision 6);
  `timeout or self._timeout` truthiness (0 falls back); 429-exhaustion raise shape
  verbatim (`retry_after` + lossless body + `project_id`, NO `request_body` — matches
  `:771-780`); type-checker fallthrough raise reduced shape (`:814-820`, FF4) with
  projectId, asserted by test_execute_with_retry_fallthrough_carries_project_id
  (max_retries −1 → 0 transport calls). Catch clause is exactly the R2.10 idiom
  (`instanceof MixpanelHttpError` filter; RateLimitError/QueryError etc. pass through as
  in Python's `except httpx.HTTPError`). HTTP_ERROR details {error, request_method,
  request_url, request_params} with Python spellings. `sleep(seconds * 1000)` is the one
  unit conversion (R2.12).
- **`app_request` (`:1191-1387` vs `client/app-request.ts`)** — AC1 guard on
  both-not-None (NOT truthiness); `request_body = form_body if form_body is not None else
  json_body` (is-not-None — correctly DIFFERENT from `_execute_with_retry`'s `or`); per-call
  `getAuthHeader()` (R2.9); NO query_origin; 204 → `{status:"ok"}` checked BEFORE 429, as
  in source; own 429 loop with the shared trio; 429-exhausted raise omits request_body
  (site shape `:1314-1323`); 422 → QueryError "Unprocessable entity" WITH request_body;
  else delegate to `handleResponse`; unwrap gated on `!raw && isPlainRecord && Object.hasOwn`
  (watchlist §8.7). Fallthrough raise reduced shape per `:1381-1387`.
- **`_request_headers` (`:452-481` vs `client/headers.ts`)** — 4-layer merge in order:
  (1) User-Agent, (2) env pair gated on `custom_name and custom_value` truthiness,
  (3) session headers, (4) caller extras; later layer wins on collision; case-sensitive
  like `dict.update`; fresh dict per call. Env arrives via per-call injected provider
  (R9.1 — Python re-reads os.environ per request; provider invoked per call). QUERY_ORIGIN
  byte-identical to `client_metadata.py:13`. UA structure ported with runtime tag `ts` —
  sanctioned (headers_contain subsets; B0-notes decision 8). Both
  TestSessionHeadersOnOutboundRequests tests translated 1:1; the config/bridge attachment
  classes correctly left for B8 per the packet.
- **`_iter_jsonl_lines` (`:109-148` vs `client/jsonl.ts`)** — byte buffer, split on 0x0A,
  per-line decode with replacement, `pythonStrip`, skip-empty, tail flush. The
  `ignoreBOM: true` divergence-fix (WHATWG decoders eat a leading U+FEFF; Python's utf-8
  codec never does) was found LIVE by the B0-2 fuzz (RUN record item 3) and is a fix
  TOWARD Python, locked by a unit test. Correct.
- **`ENDPOINTS`/`_build_url` (`:151-172`, `:417-432` vs `client/url.ts`)** — table
  byte-identical (12 URLs); leading-`/` normalization identical (empty path → `"/"`,
  matching `"".startswith("/") is False` — the `_build_url("engage", "")` call site).
  String concatenation only (R2.13).
- **`maybe_scoped_path` (`:1637-1664` vs `client/scope.ts`)** — `workspaceId !== null`
  guard (id 0 scopes; watchlist §8.6); template concat; `require_scoped_path`/
  `resolve_workspace_id` correctly deferred to B4-C1.
- **`parseLossless` relocation** — `git diff` of the moved parser + json-value model vs
  the pre-B0 rig files: **byte-identical** (headers aside); rig files are re-export shims;
  `grep` confirms the library never imports from the rig (GF5 direction). GATE-R5 grep:
  zero `response.json()` / bare `JSON.parse` on response text in `packages/*/src` (the
  only `JSON.parse` is lossless-json.ts:233 decoding a regex-validated STRING token inside
  the parser itself — pre-existing, not a body parse).
- **errors.ts** — `responseBody` widened to `unknown` (type-level only; Python's
  `str | dict | None` annotation is a runtime lie — lists/scalars pass through). Verified
  no behavior change.

### 1.2 pythonCompat vs CPython (independent probes, this machine, CPython 3.14.6)

Ran my own probe script (`/tmp/b0_probe_int.py`) against `uv run python` — 30 int cases +
29 float cases + whitespace-table sweep. ALL of the B0-notes "locked design decision 4"
probe claims reproduce, including the traps the task names:

- `int("\x1c42")`/`int("42\x1f")` **reject** (U+001C-1F isspace-vs-numeric trap);
  `str.strip()` DOES strip them (29-codepoint isspace table matches
  `whitespace.gen.ts` exactly: 0x09-0x0d, 0x1c-0x1f, 0x20, 0x85, 0xa0, 0x1680,
  0x2000-0x200a, 0x2028/29, 0x202f, 0x205f, 0x3000).
- `int("﻿42")` rejects; `int("\x8542") == 42`; `int("\xa042　") == 42`
  (non-ASCII whitespace folds to space; U+FEFF is not whitespace to Python).
- Nd digits: `int("٤٢") == 42`, `int("١_٢") == 12`, `int("𝟘𝟙") == 1` (U+1D7D8 run present
  in `decimal-digits.gen.ts:86`); `"²"`/`"〇"` reject (not Nd).
- Underscore rules: `1_0` ok; `1__0`/`_1`/`1_`/`+_1` reject; `00_0` == 0.
- Float grammar: `.`/`.e1`/`5_.`/`1e_1`/`1e1_`/`1._5`/`1_.5`/`1.5e_5` reject;
  `1.`/`.5`/`1.e1`/`1_0.`/`1_0e1_0`/`1e١`/`٤.٢` accept; `1e400` → inf; signed
  case-insensitive inf/infinity/nan incl. `\xa0inf\xa0`; `\x1cinf` rejects; `-0.0`
  preserved.

Then ran an 85-case targeted DIFFERENTIAL probe (`/tmp/b0_fidelity_probe.py`) of the same
exotic inputs through BOTH oracle bridges (`compat.python_int/python_float/python_strip/
cp_slice/sorted_strings/cp_length`), including cp_slice at non-BMP cut points, negative/
clamped/inverted bounds, tri-state None bounds, surrogate-adjacent sort inputs
(`"퟿"`, `""`, `"｡"` vs `"😀"`), prefix-tie sorts, and lone-non-BMP length:
**85/85 identical, 0 divergences.**

`cpSlice` surrogate handling verified by code read (Array.from codepoint expansion; never
splits a pair) AND by probe (`cp_slice("a𝒳b", 0, 2) == "a𝒳"` both sides).

Python reference wrappers verified binding-honest: `pycompat_ref.python_int/float/strip/
sorted_strings/cp_length/cp_slice` delegate directly to `int()`/`float()`/`.strip()`/
`sorted()`/`len()`/`value[start:end]` — CPython IS the oracle. TS bindings call the real
`packages/core` entry points with kwarg plumbing only; `compat.python_float` output
encoding mirrors the Python wrapper's two translations exactly (non-finite repr sentinels;
finite as `JsonNumber(pythonFloatStr(v))`).

### 1.3 R10.9 harness re-runs (GF6 — both reproduce)

- **B0-1** `throwaway/b0-1/run-fuzz.sh`: reproduced **3,053 examples / 0 skips /
  0 divergences** (python_int 513, python_float 514, python_strip 507, sorted_strings 507,
  cp_length 504, cp_slice 508) — byte-matches RUN.md; probe_apis.py: all six apis answer
  call DATA on both bridges, identical outputs.
- **B0-2** `throwaway/b0-2/run-fuzz.sh`: edge harness **47/47 PASS** (all
  `_handle_response` status branches from the packet checklist incl. 403 bug-compat,
  429-hostile/huge-capped, 302→HTTP_ERROR, network-error, 204-app, AC1); jsonl_chunks
  fuzz **511 examples / 0 skips / 0 divergences**; both-bridge probe identical.
- `conformance/differential/repros/` contains only the two P2-9 artifacts (committed at
  `2d80135`, pre-B0) — no open B0 repros; the B0-2 BOM repro was removed after its fix
  per the RUN record.
- TS conformance re-run: **3,251 vectors — 539 PASS / 0 FAIL / 2,712 UNPORTED @ b5c1369**
  (= 533 + the 6 jsonl-chunk vectors), matching the notes. batch-status carries the
  exact-name `api_client._iter_jsonl_lines → done` entry; P3-5 rule-4 collision scan run
  by me: no other corpus api name startsWith that entry.
- Unit suites: `packages/core/test/{client,compat}` 300/300 green;
  `conformance/tests/test_pycompat_ref_b0.py + test_registry.py + test_fuzz_harness.py`
  148/148 green.

### 1.4 R10.7 sweep (no improvements over Python)

Checked every candidate: 403 scalar TypeError + list-membership bug reproduced (not
fixed); caller-params mutation reproduced; `-0` int normalization matches Python;
`-0.0` float preserved; raise_for_status covers 3xx exactly like httpx; blank-message
fallback order matches; jsonl BOM behavior corrected TOWARD Python. The only behavioral
deltas found are Findings 1-3 below and the two documented sanctioned items
(UA runtime tag `ts`; integral-float `str()` rendering "42" vs "42.0" in message text
only — R5.4 out of contract, documented at `jsonValuePythonStr`'s JSDoc).

---

## 2. Findings

### F1 (MAJOR, latent): `parseLossless` rejects `NaN`/`Infinity`/`-Infinity`, which every Python body-parse site ACCEPTS

Evidence: `packages/core/src/client/lossless-json.ts:32` (`NUMBER_TOKEN` is strict RFC
8259) vs CPython probe run this session: `json.loads("NaN") == nan`,
`json.loads('{"a": NaN}') == {'a': nan}`, and
`httpx.Response(200, content=b'{"a": NaN, "b": Infinity}').json()` parses — i.e.
`response.json()` at `api_client.py:546`, `:766`, `:1309`, `:1340` accepts Python-style
non-finite tokens that `parseBody` (internals.ts:325-332) and the app-request 422 path
(app-request.ts:222-228) turn into a truncated-STRING body.

Divergences this produces:
- 200 body `{"a": NaN}`: Python returns the dict; TS raises `MixpanelHeadlessError`
  code `INVALID_RESPONSE` (crash-vs-success).
- 400/403/404/5xx body `{"error": "x", "b": Infinity}`: Python `response_body` is a dict
  and `_error_message` reads `error`; TS `response_body` is the raw text string and the
  message becomes the `[:200]` slice — different detail-bag SHAPE and message branch.
- 403 body `Infinity` (bare): Python → truthy float → the R10.7 TypeError; TS → string
  `"Infinity"` → QueryError. The bug-compat branch itself diverges.

Not vector-observable today (D6 rule 5 bars non-finite tokens from vector JSON), but
real Mixpanel responses have carried NaN before (P2-6's FlowsResult "NaN" bug-compat
precedent), so Phase-4 live parity can hit it. NOT mentioned anywhere in B0-notes —
undocumented divergence. Remedy is constrained by GATE-R5 (the fix is to extend
`parseLossless`/`JsonNumber` with the three `json.loads` non-finite tokens, a rig-wide
design decision the canonicalizer must weigh in on) — arbiter call required; at minimum
it must enter the B0 notes / playbook discrepancy log with a B4-before-live deadline.

### F2 (minor, documented-but-misjustified): Retry-After > 2^53−1 reads as ABSENT in TS

Evidence: `backoff.ts:126-146` maps BOTH `pythonInt` codes (incl. `PY_INT_UNSAFE_INTEGER`)
to null; CPython parses `int("9007199254740993")` fine (probed). For a hostile header
above 2^53−1, Python sleeps `min(x, 60) = 60` unjittered and reports the RAW huge int in
`RateLimitError.retry_after`; TS takes the JITTERED exponential fallback and reports
`retry_after: null`. Sleep-path difference is not vector-observable; the detail-bag
difference is real. B0-notes decision 7 documents it and flags it for this review — good —
but the playbook-packet justification it cites ("no B0 consumer can produce one
legitimately") is false for attacker-controlled headers, which the packet itself calls
attacker-controlled. Arbiter should either bless it into the discrepancy log as a
sanctioned deviation (my recommendation — the 60s cap makes it behaviorally inert for
sleeping, and `details_contain` never asserts retry_after for such headers) or require
`parseRetryAfter` to catch `PY_INT_UNSAFE_INTEGER` distinctly.

### F3 (minor, observation-grade): `parseBody` catches ALL parse errors; Python catches only `json.JSONDecodeError`

Evidence: internals.ts:325-332 bare `catch`; `api_client.py:545-548` catches
`json.JSONDecodeError` only. A pathologically deep body (~1000+ nesting) raises
`RecursionError` through Python's `_handle_response`; TS either parses it fine (V8 stack
is deeper) or swallows a `RangeError` into the body-as-text path. Success-vs-crash
divergence on unrealistic input; technically an R10.7 "improvement". Recommend a one-line
comment at `parseBody` acknowledging the delta; no code change warranted.

### Non-findings verified and accepted (for the arbiter's record)
- Non-numeric `project.id` in the 403 flag branch: Python `int()` ValueError vs TS coded
  error — unreachable with validated Project ids.
- `_error_message` non-string `error` rendering for integral FLOAT tokens ("42" vs
  "42.0") — message text only, R5.4, documented in-code.
- Commit-count deviation from "one commit per repo" — process matter, flagged in notes
  (deviation 1/decision 8), stamp mechanics justify it; gates-lens territory.
- Layer-3 entry-point substitution list (B0-notes decision 13) spot-checked: the deferred
  tests (`TestRetryStateResetRegression`, stream `:1883-1891` raise-site tests,
  form-encoding content-type) genuinely have B4 subjects; their B0-relevant assertions
  (fallback-not-sleep on negative/garbage headers) are present in backoff/internals tests.

## 3. Reproduction commands

```bash
# CPython ground truth (this session's probe files)
uv run python /tmp/b0_probe_int.py
# 85-case both-bridge differential probe (from the Python repo root)
uv run python /tmp/b0_fidelity_probe.py         # -> 85 probes, 0 divergences
# RUN-record re-runs
(cd ../mixpanel-headless-ts && bash throwaway/b0-1/run-fuzz.sh)   # 3,053 / 0 div
(cd ../mixpanel-headless-ts && bash throwaway/b0-2/run-fuzz.sh)   # 47/47 + 511 / 0 div
(cd ../mixpanel-headless-ts && npm run conformance)               # 539 / 0 / 2712
```
