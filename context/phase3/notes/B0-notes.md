# B0 batch notes

## B0-1 pythonCompat completion — work log

- [ ] survey existing compat structure (TS) + pycompat_ref/registry/strategies (Py)
- [ ] TDD: vitest tests first (python-int, python-float, python-strip, codepoint)
- [ ] gen tables: decimal-digits.gen.ts, whitespace.gen.ts (pinned CPython 3.14.6 / Unicode 16)
- [ ] TS impls
- [ ] Python pycompat_ref wrappers + registry _gate_entries
- [ ] authored vectors conformance/vectors/authored/compat/
- [ ] oracle strategies + oracle-ts registration (bindings)
- [ ] corpus re-extract + re-sync + re-pin (P3-7) + D9 drift check + P3-1 count update
- [ ] R10.9 throwaway harness + RUN record
- [ ] just check + npm run check green; commits

## Locked design decisions (B0-1, from source/probes 2026-08-15)

1. Error contract for compat parse apis (R5.5 excludes uncoded ValueError from vectors;
   emit._encode_error returns None for it -> corpus runner would FAIL): both sides raise
   MixpanelHeadlessError with ad-hoc codes (precedent: HTTP_ERROR/INVALID_RESPONSE
   ad-hoc codes on the base class, not in coded_guard_registry):
   - PY_INT_INVALID_LITERAL (int parse failure)
   - PY_INT_UNSAFE_INTEGER (|result| > 2^53-1; canonicalizer 2^53 policy R4.5)
   - PY_FLOAT_INVALID_LITERAL (float parse failure)
2. Non-finite pythonFloat results cannot ride vectors (D6 rule 5, encode + canonicalize
   both reject). Sentinel: the PYTHON REFERENCE WRAPPER returns repr(result) for
   non-finite ("inf"/"-inf"/"nan"); TS binding mirrors. TS library pythonFloat itself
   returns the real number (Infinity/-Infinity/NaN) - CPython semantics for consumers.
3. Float outputs and canonical float-ness: Python encodes top-level integral float
   output as raw token 42.0 (in_rich_payload=False) -> canonical "42.0"; a plain TS
   number 42 canonicalizes "42". TS binding for compat.python_float returns
   new JsonNumber(pythonFloatStr(v)) for finite results so canonical forms match.
4. CPython 3.14.6 probes (empirical, this machine, uv-managed 3.14.6):
   - int()/float() whitespace = str.isspace() MINUS {0x1c,0x1d,0x1e,0x1f} (probe:
     int-rejects those four; accepts \t\n\v\f\r space + all non-ASCII isspace).
     U+FEFF rejected. str.strip() strips all 29 isspace cps incl 0x1c-0x1f.
   - underscores strictly between digits, both grammars; "1_0e1_0" float-ok/int-VE;
     "1_.5","1._5","1.5e_5","1e5_ ..." all VE. int("00_0")=0.
   - non-ASCII Nd digits accepted by BOTH int() and float() incl. in exponents
     (transform-decimal-and-space-to-ASCII); "²"/"〇" rejected (not decimal).
   - float grammar: mantissa DIGITS'.'?|DIGITS?'.'DIGITS, "."/".e1" VE, "1.e1" ok;
     inf/infinity/nan case-insensitive with sign; "1e400" -> inf (never OverflowError).
5. Re-pin mechanics (P3-7 trigger 1): commit P1 (Python semantic changes), then
   re-extract manifest with --mp-record-commit=<P1 sha> --mp-record-date=2026-08-15,
   authored $bundle stamped <P1 sha>, commit P2 "corpus: re-extract @ <P1sha>"
   (precedent c4bc884/8ae76314); TS pin -> <P1 sha>, sync-corpus, api-map regen.
   D8/D9 drift check: recorded bundles byte-identical except manifest stamps.
6. Fuzz targets: six new Phase-3 targets (python_int, python_float, python_strip,
   sorted_strings, cp_length, cp_slice) so the >=500-per-family budget is per-target;
   test_fuzz_harness ALL_TARGETS assertion extended with the PHASE3 tuple.
7. cp_slice kwargs: start/end null OR absent both mean Python None (rig-api tri-state
   note documented at the binding).
8. Commit plan deviates from the packet's "one commit per repo" line by necessity of
   the stamp mechanics (self-referential SHA): Python P1 impl + P2 corpus re-extract
   (+P3 docs); TS T1 compat module, T2 rig re-pin/bindings, T3 throwaway+RUN.

## Environment note (pre-existing, NOT a B0-1 regression)
- Running `python -m pytest conformance/runner conformance/tests` in ONE pytest
  invocation makes test_oracle_protocol TestSubprocessRoundTrip time out on
  process.wait(30) — reproduced identically at HEAD~1 (6bd88b5) in a clean
  worktree. The CI-parity recipe (`just conformance`) runs the two suites as
  SEPARATE invocations and is green. Left as-is; flagged for the review pair.

## B0-1 RESULTS (2026-08-15)

Commits:
- Python ts-port/phase2-contract-support:
  - b5c1369 "B0-1: pythonCompat completion (Python side)" — pycompat_ref wrappers,
    registry _gate_entries (9 compat names), 6 PHASE3 fuzz targets, gen_b0_vectors.py,
    90 new unit tests (conformance/tests/test_pycompat_ref_b0.py).
  - f507aba "corpus: re-extract @ b5c1369 + B0-1 authored compat vectors (72)".
- TS main:
  - b67ce85 compat module (python-int/python-float/python-strip/codepoint +
    numeric-parse + decimal-digits.gen.ts (76 runs/760 cps) + whitespace.gen.ts
    (29 str / 25 numeric cps) + generator scripts; 74 vitest cases w/ fast-check).
  - 96dd73c rig: re-pin @ b5c1369, sync-corpus, 6 bindings, authored-apis +6,
    api-map regen (413 entries).
  - e451cc0 throwaway/b0-1 harness + RUN record.

R10.9 harness RUN record (mirrored from mixpanel-headless-ts/throwaway/b0-1/RUN.md):
- Fuzz oracle-py vs oracle-ts, derandomize=True (seedless deterministic),
  --examples 500 per target: python_int 513, python_float 514, python_strip 507,
  sorted_strings 507, cp_length 504, cp_slice 508 = 3,053 examples, 0 skipped,
  0 divergences, no new repros. Edge sets ride as @example decorators
  (strategies.py PHASE3_TARGETS edge_calls; str-domain omissions documented there).
- Mechanical probe: one oracle.call per new api on BOTH bridges — all six answered
  call DATA, identical outputs (throwaway/b0-1/probe_apis.py).
- Vector replay: Python runner 3,251/3,251 PASS; TS conformance 533 PASS / 0 FAIL /
  2,718 UNPORTED @ corpus b5c1369.

Deviations / review-pair flags:
1. "One commit per repo per packet" (P3-4 common criteria) split into 2-3 commits per
   repo — forced by the stamp mechanics (a bundle cannot carry its own commit SHA;
   precedent e73f303/c4bc884) and by keeping the corpus re-extract a deliberate,
   separately-reviewable act (D3).
2. Ad-hoc error codes PY_INT_INVALID_LITERAL / PY_INT_UNSAFE_INTEGER /
   PY_FLOAT_INVALID_LITERAL live at the raise sites (pycompat_ref + TS compat), NOT in
   exceptions.CODED_GUARD_REGISTRY (precedent: HTTP_ERROR / INVALID_RESPONSE in
   api_client.py). If the arbiter wants them contract-listed, that is a
   generate_contract extension, not a behavior change.
3. Authored bundle uses ensure_ascii=True framing (oracle ASCII-safe precedent):
   several inputs carry U+0085/U+2028-class codepoints that str.splitlines() treats
   as line breaks — raw UTF-8 emission corrupted JSONL framing (found live when the
   Python loader split a NEL inside a vector line; emit.py's ensure_ascii=False is
   safe only because recorded strings never carry those codepoints at present).
4. Pre-existing combined-invocation pytest flake (see Environment note above).

---

# B0-2 — shared client internals (R10.8) — running notes

Status: IN PROGRESS (skeleton). Assembled incrementally per R10.13.

## Scope (playbook P3-4 packet B0-2)
- TS home: packages/core/src/client/{internals,jsonl,backoff,url,headers,scope,app-request,lossless-json}.ts
- Python source of record: src/mixpanel_headless/_internal/api_client.py @ support-branch HEAD (post-PR-206)
  - _error_message :81-106; _iter_jsonl_lines :109-148; ENDPOINTS :151-172; _build_url :417-432;
    _request_headers :452-481; _handle_response :503-662; _calculate_backoff :664-681;
    _retry_wait_seconds :683-704; _execute_with_retry :706-820; _parse_retry_after :1159-1185;
    app_request :1191-1387; maybe_scoped_path :1637-1664; client_metadata.py (QUERY_ORIGIN, get_user_agent)
- parseLossless relocation: conformance-runner/src/lossless-json.ts -> packages/core/src/client/lossless-json.ts (GF5)
- Binding: api_client._iter_jsonl_lines (6 authored chunk vectors, corpus/authored/streaming/jsonl-chunks.jsonl)
- batch-status: add exact-name entry api_client._iter_jsonl_lines -> done

## Work log
- [x] Read playbook v1.1 fully + review-resolution + rulebook
- [x] Read Python source ranges (all cited above)
- [x] Survey TS phase-2 infra (errors, session/auth model, compat, rig)
- [x] Layer-3 test translation (TDD first)
- [x] Implementation
- [x] Binding + batch-status entry + vectors green (539/0/2712)
- [x] R10.9 throwaway harness + RUN record (see below)
- [x] npm run check green
- [ ] just check (Python) + commits

## Design decisions (running)
1. **Seam shape**: B0 ports the internals as free functions over minimal dependency
   bags (`RequestExecutor`, `sleep(ms)`, `random()`, `requestHeaders(extra)`,
   `projectId`) - NOT a client class. B4-C1 builds `createMixpanelClient` + the
   fetch adapter over these by name (R10.8). The injected `request` executor is
   contractually required to throw `MixpanelHttpError` for transport failures
   (R2.10 - adapter-owned normalization); `_execute_with_retry`'s catch is the
   R2.10 idiom `if (!(e instanceof MixpanelHttpError)) throw e;`.
2. **MixpanelHttpError lands in B0** (`client/internals.ts`), extending `Error`
   (NOT MixpanelHeadlessError) - it mirrors `httpx.HTTPError`, an out-of-hierarchy
   transport error that `_execute_with_retry`/`app_request` always wrap into
   `MixpanelHeadlessError` code `HTTP_ERROR`. errors.ts said "deferred to B4";
   pulled forward because the B0 catch clauses need the class.
3. **parseLossless relocation** takes `json-value.ts` (JsonNumber/JsonValue) along
   (the parser's value model); rig files become thin re-export shims so
   `instanceof JsonNumber` identity is preserved rig-wide. Unit tests move to
   `packages/core/src/client/lossless-json.test.ts`.
4. **`_handle_response` body model**: parsed bodies are `JsonValue` (JsonNumber
   tokens intact, GATE-R5). `isinstance(body, dict|list)` translates to
   plain-record/array checks that EXCLUDE JsonNumber instances. errors.ts
   `responseBody` option/field types widened to `unknown` (Python's annotation
   `str | dict | None` is a lie at runtime - `response.json()` returns lists and
   scalars too, and Python passes them through).
5. **403 scalar-body TypeError reproduced** (R10.7): Python
   `body_text = json.dumps(body) if isinstance(body, dict) else (body or "")`
   raises `TypeError` when the parsed 403 body is a truthy non-dict non-str
   (`42`, `1.5`, `true`) because `in` is applied to a non-container; a LIST body
   does Python element-membership (flag only matches as an exact element).
   TS reproduces: Python-truthiness helper + TypeError throw + comment; filed for
   a Python-side issue (NOT fixed in TS alone).
6. **`params` caller-dict mutation reproduced**: `_execute_with_retry` writes
   `params["query_origin"] = QUERY_ORIGIN` into the CALLER's dict (after None->{}
   defaulting). TS mutates the passed object identically (observable behavior).
7. **Retry-After >2^53**: `pythonInt` throws `PY_INT_UNSAFE_INTEGER` where CPython
   parses arbitrarily large ints; per the playbook packet ("no B0 consumer can
   produce one legitimately"), both PY_INT error codes map to `null` (header
   treated as absent). Behavioral difference vs Python exists only for headers
   with >2^53 seconds; documented here for the review pair.
8. **User-Agent**: vectors assert headers via `headers_contain` subsets (UA is
   never byte-locked); `getUserAgent()` ports the STRUCTURE
   (`mixpanel-headless/{version} (entry={lib|cli}; ...)`) with runtime tag `ts`
   replacing `python/x.y`, version pinned to packages/core/package.json (0.0.0).
   `QUERY_ORIGIN` stays byte-identical ("mixpanel-headless") - it IS wire-locked.
   `set_entry_point`/`get_entry_point` module state ported alongside.
9. **ENDPOINTS** as nested `ReadonlyMap` (R4.8) + `endpointBase(region, kind)`
   accessor using `invariant` (R6.8); `buildUrl` is a pure string-concat builder
   (R2.3/R2.13).
10. **Env layer of `_request_headers`** is injected (`getCustomHeaderEnv()`
    provider re-read per call, mirroring Python's per-request `os.environ` read)
    - core reads no env (R9.1/R9.4); the node package supplies the real reader in
    B8, tests inject.
11. **`_iter_jsonl_lines`** -> `async function* iterJsonlLines(source:
    AsyncIterable<Uint8Array>)` over DECODED bytes (httpx decompresses before
    `iter_bytes()`; the binding owns gzip via `DecompressionStream`, mirroring
    conformance/record/adapters.py's httpx-response rebuild). TextDecoder
    (non-fatal) is the sanctioned `errors="replace"` mapping per the packet.
12. **oracle-ts async bindings**: `handleLine`/`dispatch`/`executeBound` become
    async (awaiting binding results) so `api_client._iter_jsonl_lines` - a
    registry-covered api with an oracle-py surface - is fuzzable through BOTH
    bridges (P3-2(c)). This closes the server's own "out of oracle scope until
    Phase 3" note; rig change at fable tier per P3-3.
13. **Layer-3 entry-point substitution**: Python tests drive the B0 internals
    through thin B4 wrappers (`get_events`, `request()`, `sign_replays`,
    `export_events`). Translations preserve every assertion but invoke
    `executeWithRetry`/`appRequest`/`handleResponse` directly; per-file headers
    document the substitution (phase2-audit A2 style). Tests whose SUBJECT is
    B4 streaming/pagination state (TestRetryStateResetRegression incl.
    test_stream_rate_limit_error_carries_project_id, the export-stream
    Retry-After case) defer to B4 - their raise site (:1883-1891) is B4 code;
    noted so B4-C2 picks them up.

## R10.9 RUN record (B0-2)

Driver: `throwaway/b0-2/run-fuzz.sh` (TS repo; derandomized, re-runnable —
the review pair re-runs this exact command).

1. **Deterministic wire edge set** (`throwaway/b0-2/edge-harness.ts` via
   `run-edge-harness.mjs`): 47 cases, 47 PASS / 0 FAIL. Every
   `_handle_response` status branch from the packet's verbatim list
   (200-object, 200-array, 200-non-JSON, 200-empty, 400, 401, 403-plain,
   403-sensitive-data, 403-sensitive-string, 403-list-exact,
   403-list-substring, 403-truthy-scalar TypeError bug-compat,
   403-falsy-scalar, 404, 412, 422-via-app_request, 429-exhausted,
   429-then-200, 429-no-header-backoff, 429-hostile, 429-huge-capped, 500,
   503-string-body, 302-redirect-manual->HTTP_ERROR, network-error, 204-app,
   app unwrap/raw/no-results, app-429/transport/401, AC1 guard) + the R10.9
   value edges as 200 scalar bodies (42, 18.0, 1.5, true, null, "ok", [],
   "", non-BMP) + 5 in-process jsonl line cases. Replayed through
   `createVectorFetch` hand-built interactions -> a minimal
   fetch->WireResponse adapter (R2.10/R2.11 prototype, throwaway-only) ->
   the REAL `executeWithRetry`/`appRequest`/`handleResponse`.
2. **Oracle-bridge fuzz** — `jsonl_chunks` family
   (`api_client._iter_jsonl_lines`, the ONE B0-2 api with an oracle call
   surface; the wire internals are bridge-exempt per the packet):
   Hypothesis derandomize=True, 500-example budget -> **511 examples, 0
   skips, 0 divergences** on the final run (edge set attached as @example
   decorators: empty chunk list, empty chunk, blank-lines, CRLF,
   mid-codepoint split, R10.9 literals as lines, \x1c strip-set lines,
   invalid UTF-8, encoded-surrogate bytes, gzip chunk-boundary split).
3. **DIVERGENCE FOUND AND FIXED mid-run** (the R10.9 payoff): first fuzz
   run diverged at example 58 — input `b"\xef\xbb\xbf\n"`: Python
   `bytes.decode("utf-8")` keeps a leading U+FEFF (only utf-8-sig strips,
   and U+FEFF is not in `str.strip()`'s whitespace set) -> yields
   `["\ufeff"]`; WHATWG `TextDecoder` EATS a leading BOM by default ->
   yielded `[]`. Fix: `new TextDecoder("utf-8", { ignoreBOM: true })` in
   `client/jsonl.ts` + a locking unit test (jsonl.test.ts BOM case).
   Shrunken repro was written to `conformance/differential/repros/
   2026-08-15-api_client-_iter_jsonl_lines.json` and removed after the
   fix + green re-run (repros block the task while present).
4. **Mechanical both-bridge probe** (`throwaway/b0-2/probe_apis.py`):
   `api_client._iter_jsonl_lines` answers call DATA on oracle-py AND
   oracle-ts with identical outputs.
5. Vector replay after binding: TS conformance **3,251 vectors — 539 PASS /
   0 FAIL / 2,712 UNPORTED** @ corpus b5c1369 (exactly 533 + the 6 authored
   jsonl-chunk vectors; UNPORTED down by 6 per the P3-1 B0 row).

## Deviations / review-pair flags (B0-2)
1. errors.ts responseBody typing widened to `unknown` (see decision 4) - a
   Phase-2 surface touch, type-level only.
2. oracle-ts made async-capable (decision 12) - rig change beyond the literal
   packet text, needed for the packet's own oracle-fuzz mandate on jsonl.
3. B4 hand-off list: TestRetryStateResetRegression (4 tests),
   test_export_events_negative_retry_after_uses_backoff, form-encoding
   content-type assertion in test_form_body_sent_as_form_encoded (adapter-owned),
   auth-header wire capture tests (Bearer/Basic recorded end-to-end at B4;
   B0 locks the per-request `getAuthHeader()` seam call pattern).
4. R10.7 Python-side issue to file (bug reproduced verbatim in TS, never
   fixed TS-alone): `_handle_response` 403 branch `(response_body or "")`
   + `in` raises TypeError for truthy non-dict non-str JSON bodies
   (`42`/`1.5`/`true`), and a LIST body silently uses element-equality
   membership. Locked by internals.test.ts R10.7 cases + edge harness.
5. Retry-loop tests that Python pinned via `monkeypatch.setattr(client,
   "_calculate_backoff", ...)` assert the injected-RNG-deterministic
   backoff value instead (zero-jitter attempt-0 = 1s -> 1000ms at the
   sleep seam); the assertion content (negative/garbage header never
   reaches sleep; fallback path taken) is unchanged.
6. eslint.config.js: node-globals block extended to `throwaway/**/*.mjs`
   (harness driver); removed with `throwaway/` at the batch gate.

## Arbiter resolution addendum (2026-08-15, b0-review-resolution.md)

Review pair verdicts: both GO; arbiter GO — B0 signed off. Per-finding record
(full rationale in `context/phase3/design/b0-review-resolution.md`):

1. **F1 FIXED (major)**: `parseLossless` now accepts json.loads' non-finite
   constants `NaN`/`Infinity`/`-Infinity` behind the opt-in `pythonConstants`
   flag (native non-finite numbers — exactly Python's floats), enabled at the
   three wire body-parse sites only; rig vector loading stays strict (D6 rule 5).
   13 new red-first tests; conformance unchanged (539/0/2712 @ b5c1369).
2. **F2 BLESSED**: Retry-After >2^53−1 null-vs-raw-big-int deviation is now
   playbook Discrepancy #6 with a CORRECTED justification — decision 7 above
   cited the packet's "no B0 consumer can produce one legitimately", which is
   wrong for attacker-controlled headers; the real shield is the R4.5 2^53
   policy + the 60s sleep cap + zero vector/Layer-3 exposure.
3. **F3/assertions-2 FIXED**: the three JSONDecodeError-analog catches now
   carry the `instanceof LosslessJsonError` guard (RangeError = RecursionError
   analog propagates; backoff.ts pattern), locked by 1M-deep-nesting tests.
4. **assertions-1 FIXED**: jsonl.test.ts header now cites
   TestIterJsonlLines (:2709-2877) as a translation source.
5. **cp_length budget BLESSED**: combined-bullet reading (≥10 across
   cp_slice+cp_length; the bullet's named case families are slice-shaped).
6. **Carried to B4** (gate must verify): (a) R6.7 AbortSignal satisfied via
   signal-aware `request`/`sleep` closures without touching B0 signatures —
   state this in the B4-C1 packet; (b) deviation-3 deferrals above actually
   land at B4 (TestRetryStateResetRegression ×4, streaming project_id raise
   :1883-1891 lock, negative-retry-after export case, form content-type,
   auth-header wire captures).

---

# B0 batch gate (P3-2 step e) — attempt 1, 2026-08-15

**RESULT: GATE FAIL (BLOCKED) at step (4)** — the fresh-seed differential
full-suite regression found ONE real divergence (a Phase-2 TS types-layer
bug, repro committed). Steps (1)–(3) and (5) all passed; step (6)
`throwaway/` cleanup and the gate/checkpoint commits were deliberately NOT
performed (the gate did not close — the report-JSON archive under
`context/phase3/reports/` and the throwaway removal belong to the passing
gate run).

## Gate step results
- [x] (1) batch-status — PASS. Flip state confirmed: exact-name entry
  `api_client._iter_jsonl_lines` -> `done` already in the table (landed in
  the B0-2 commit per the packet's own done-criteria: "NO batch-status flip
  … beyond the exact-name entry, which IS added as done"); `compat.` has
  been `done` since Phase 1/2 and the table is PREFIX-granular, so the 6 new
  `compat.*` api names (python_int/python_float/python_strip/sorted_strings/
  cp_length/cp_slice) are covered with no name-granular extension needed.
  Standing no-prefix-collision assertion (P3-5 rule 4) run mechanically over
  all 419 corpus api names: the ONLY name with
  `startsWith("api_client._iter_jsonl_lines")` is the exact name itself — no
  pending name is captured. Corpus per-prefix re-measure sums to exactly
  3,251 (matches the P3-1 B0-1 re-pin follow-up).
- [x] (2) conformance checkpoint — COUNTS MATCH. `npm run conformance` @ TS
  main 629721b / corpus b5c1369: **3,251 vectors — 539 PASS / 0 FAIL /
  2,712 UNPORTED** (= Phase-2 461 + 72 authored compat + 6 jsonl-chunk; the
  B0 gate delta of 6-recorded-equivalent + authored per the P3-1 B0 row).
  Report NOT archived to `context/phase3/reports/` — that archive is the
  gate-closing checkpoint commit artifact (P3-2e item 2) and the gate is
  blocked; numbers recorded here instead.
- [x] (3) oracle surface (GF4) — PASS. Mechanical `oracle.call` probes, one
  per newly registered api on BOTH bridges (`throwaway/b0-1/probe_apis.py` +
  `throwaway/b0-2/probe_apis.py`): 7 apis (6 `compat.*` + 
  `api_client._iter_jsonl_lines`) x 2 bridges = **14/14 non-"unknown api"
  call-DATA responses**, outputs pairwise identical.
- [x] (4) differential full-suite regression — **FAIL (1 real divergence)**.
  Fresh seed **52794688** (recorded; run reproduces exactly), cumulative
  surface (all 22 `ALL_TARGETS` families), P2-9 budget >=500/family:
  **11,294 examples, 3,049 skips (all explained — the six Phase-1 families
  whose apis are B2/B3-pending on oracle-ts, protocol §4.2), 1 divergence.**
  Full record + triage: `conformance/differential/oracle/RUN.md` + raw JSON
  `conformance/differential/oracle/2026-08-15-b0-gate-attempt1.json`; repro
  `conformance/differential/repros/2026-08-15-types-RetentionEvent.json`
  (BLOCKS the gate while present). Harness gained a `--seed` option for this
  (fable rig change, TDD: `TestSeededRuns`, 3 tests red-first; `seed=None`
  preserves the historical derandomized mode byte-for-byte).
- [x] (5) referees — NOT REQUIRED at B0, per P3-7: referees (a)+(b) run at
  the B3 and B6 gates (bookmark-touching batches); B0 touched no bookmark
  construction surface (compat + client internals only). Stated for the
  record.
- [ ] (6) throwaway/ cleanup + eslint throwaway-glob revert — DEFERRED to
  the passing gate run (arbiter sign-off @ a501829 permits it, but deleting
  the harness while the gate is failing would strand the re-run/probe
  drivers the remediation + gate re-run need).
- [x] (7) checks at final HEADs — `just check` green (Python, post-commit);
  `npm run check` green (TS @ 629721b, unchanged this task — no TS commit).

## Divergence triage summary (full version in oracle/RUN.md)

`types.RetentionEvent(event=<U+0085 NEL, sole char>)`: Python
`_validate_event_name` uses `not event.strip()` -> `EV1_EMPTY_EVENT`; TS
`guards.ts:82 validateEventName` uses `!event.trim()` -> accepts (JS trim
strips neither U+001C–U+001F nor U+0085; it DOES strip U+FEFF, giving an
inverse divergence Python-accepts/TS-rejects, probed manually). Class-wide
Phase-2 defect: ~24 trim-based emptiness guards across
`packages/core/src/types/` (inventory in RUN.md). Remedy: `pythonStrip`
(B0-1, pinned whitespace.gen.ts) at every guard — TS-only fix (Python is
arbiter and correct; NOT an R10.7 event; no corpus re-pin). P2-9 missed it
because seedless derandomized generation never emitted those codepoints for
these families — the P3-7 fresh-seed mandate caught it on its first run.

## Recommended unblock path
1. Fable-tier remediation task on TS main: replace trim-emptiness guards in
   `packages/core/src/types/` with `pythonStrip`-based checks (red-first
   tests per site incl. the U+0085 and U+FEFF directions; `parseInt` site
   assessed separately); re-run retention_flow_family + sibling family fuzz
   (seed 52794688 must go clean) then a review pass per P3-2d norms for a
   Phase-2 surface touch.
2. Delete the repro after the green re-run (repros block while present).
3. Re-run this gate from step (4) (fresh seed again), then perform steps
   (2)-archive, (6) cleanup, and the gate commits (TS gate commit on main +
   Python docs/report commit).

---

# B0 gate — attempt 2 (2026-08-15): **GATE PASS**

Attempt 1 blocked at step (4) on the real trim-vs-strip divergence (record
above + `conformance/differential/oracle/RUN.md`). The unblock path was
executed exactly as written; the gate re-ran from step (4) and closed.

## Remediation (between attempts, TS main `3c07d4e`)
Fable-tier, red-first (R10.1): `pythonStrip` at all 13 trim-based emptiness
guard sites (`guards.ts` EV1 + `*2_COHORT_NAME_EMPTY`, `metric.ts` FM1,
`funnel.ts` HC1, `filter.ts` LG1+LC5, `cohort.ts` CD4+CA2+CD7,
`group-by.ts` GB1, `frequency.ts` FB1+FF1, `data-governance.ts`
alternatives), and `safeInt` (`results/query-engine.ts`) string branch
rewritten from `\s`-regex+`parseInt` to `pythonInt` with the guarded-catch
pattern (b0-review-resolution F3/A2). 15 new tests in
`strip-guards.test.ts` (all 13 sites, BOTH divergence directions, guard
ORDER lock: U+001C-only event => EV1 not EV2) + 7 safeInt CPython-grammar
tests in `flow-query-result.test.ts`; 20 red before the fix, all green
after; every expectation verified against live CPython (probe run recorded
in the remediation commit message).
- **R10.2**: zero assertions weakened — the change is purely additive
  (existing suites untouched except the appended safeInt describe).
- **Deviation (process)**: the remediation + its review-quality checks ran
  INSIDE the gate task (single fable agent) rather than as a separate
  remediation task + P3-2d review pair. Self-review executed against the
  P3-2d checklist (R10.2 diff, rulebook pass, TODO(port) triage: none
  added). FLAG for the next review pair/arbiter to spot-check
  `3c07d4e` (suggested: fold into the B2-gate review load).
- **Deviation (behavioral, needs arbiter blessing like Discrepancy #6)**:
  `safeInt` on a numeric string with magnitude >2^53−1 returns `default_`
  where CPython `_safe_int` returns the exact big int (R4.5 leaves no
  faithful representation; the OLD code returned an imprecise number
  there, which was no more faithful). Not vector- or fuzz-observable
  today (no oracle family drives `_safe_int`/`from_response`).
- **Proposed R10.4 amendment** (fix pattern recurred 13×): "Porting a
  Python blank/emptiness check (`not s.strip()`) MUST use `pythonStrip`,
  never `String.trim()`; porting `int(str)` MUST use `pythonInt`, never
  `parseInt`/`Number`/`\s`-regex grammars." For the arbiter to file.

## Gate step results (attempt 2)
- [x] (1) batch-status — PASS, unchanged from attempt 1 and re-verified
  mechanically at gate HEAD: exact-name `api_client._iter_jsonl_lines` ->
  `done` (landed at B0-2 per the packet); `compat.` prefix-granular `done`
  since Phase 1/2 covers the 6 new apis; no-prefix-collision assertion
  over all 419 corpus api names — only the exact name matches; per-prefix
  counts re-sum to exactly 3,251. No flip in the gate commit (nothing to
  flip; the P3-2e "same commit" rule is satisfied vacuously, packet-
  sanctioned).
- [x] (2) conformance checkpoint — COUNTS MATCH at BOTH final HEADs
  (remediation `3c07d4e` and gate `8f79b67`): **3,251 vectors — 539 PASS /
  0 FAIL / 2,712 UNPORTED** @ corpus b5c1369. Report JSON archived:
  `context/phase3/reports/2026-08-15-b0-gate.json`.
- [x] (3) oracle surface (GF4) — PASS, re-run at final HEADs before
  throwaway cleanup: 7 apis (6 `compat.*` + `api_client._iter_jsonl_lines`)
  x 2 bridges = **14/14 non-"unknown api" call-DATA responses**, outputs
  pairwise identical.
- [x] (4) differential full-suite regression — **PASS**. Fresh seed
  **28631260**: 22 families, **11,281 examples, 3,049 explained skips
  (protocol §4.2, six B2/B3-pending Phase-1 families), 0 divergences**.
  Attempt-1's divergent seed **52794688** re-run in full as verification:
  identical totals, 0 divergences. Records + raw JSON in
  `conformance/differential/oracle/`. Repro
  `2026-08-15-types-RetentionEvent.json` DELETED (resolved); the two
  remaining repro files are resolved P2-9 triage records and do not block.
- [x] (5) referees — NOT REQUIRED at B0 per P3-7 (referees (a)+(b) run at
  the B3/B6 bookmark-touching gates; B0 touched no bookmark construction
  surface). Stated for the record.
- [x] (6) throwaway/ cleanup + eslint throwaway-glob revert — DONE in the
  TS gate commit `8f79b67` (arbiter sign-off @ a501829; GF4 probes were
  re-run BEFORE deletion).
- [x] (7) checks at final HEADs — `npm run check` green @ `3c07d4e` and
  @ `8f79b67` (74 test files, 2,215 passed, browser smoke OK);
  `just check` green on the Python support branch at the gate commit.

**B0 BATCH GATE: CLOSED.** B2 may proceed (B2 was already unblocked at
B0-1 per P3-1; the gate closure now also releases the B0 hard barrier for
everything else in sequence).
