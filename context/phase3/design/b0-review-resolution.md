# B0 Review Resolution — arbiter (playbook P3-2 step d)

**Arbiter**: fable · 2026-08-15
**Inputs**: `b0-review-fidelity.md` (@ d290e2b) + `b0-review-assertions.md` (@ 7fa7697),
both verified independently against source + live CPython probes this session.
**Verdict**: **GO — B0 signed off.** Every finding was re-verified from source (no
reviewer claim trusted unprobed), 4 fixes APPLIED with TDD discipline (13 new tests,
red-then-green), 2 deviations BLESSED with written rationale, 0 findings rejected.
All gates re-ran green after the fixes: `npm run check` (typecheck/lint/prettier/
vitest 2,193 passed incl. the 13 new/browser smoke), conformance **3,251 — 539 PASS /
0 FAIL / 2,712 UNPORTED @ b5c1369** (unchanged — the fixes are not vector-observable,
as both reviews predicted), B0-2 edge harness re-run **47/47**. B0-1 fuzz not re-run a
third time: no compat code changed in this resolution (both reviewers already
reproduced its RUN record byte-for-byte).

Binding-honesty verification (P3-5 rule 3, arbiter duty): concur with both reviews —
independently re-checked that `bindings.ts` compat + jsonl entries call the real
`packages/core` entry points and `pycompat_ref` wrappers delegate to CPython builtins.
PASS, no change.

---

## F1 (fidelity, MAJOR) — parseLossless rejected `NaN`/`Infinity`/`-Infinity` that every Python body-parse site accepts

**Verdict: CONFIRMED → FIXED** (not deferred to the discrepancy log — B4's 800+ wire
methods all flow through these parse sites, so the latent divergence would compound
through every wire batch and Phase-4 live parity).

Verified by my own probes (CPython 3.14, this session): `json.loads` accepts exactly
`NaN` / `Infinity` / `-Infinity` (exact case; `-` only on `Infinity`; rejects `nan`,
`NAN`, `-NaN`, `+Infinity`, `infinity`, `INFINITY`, `Inf`); `httpx.Response(200,
b'{"a": NaN}').json()` parses; `json.dumps` renders the tokens back; `str(float('nan'))
== "nan"`; `bool(float('nan')) is True`; `flag in float('inf')` raises TypeError
("argument of type 'float' is not a container or iterable"). All four Python body-parse
sites (`api_client.py:546`, `:766`-region, `:1309`, `:1340`) are `response.json()` =
`json.loads` defaults.

**Fix applied** (TS repo): `parseLossless` gains an opt-in
`ParseLosslessOptions.pythonConstants` flag that parses the three constants as NATIVE
non-finite `number`s — exactly the `float('nan')`/`float('inf')` Python produces (no
raw-token precision concern exists for non-finite values, so `JsonNumber` is untouched;
widening `JsonNumber` was rejected: its `isIntegerToken`/`BigInt(raw)` paths would
landmine on non-finite raw tokens, and it is canonicalizer-shared). The flag is enabled
at exactly the three body-parse sites (`internals.ts` `parseBody`, the
`_handle_response` tail re-parse, `app-request.ts` 422) — the GATE-R5 remedy direction
(extend the parser, never `JSON.parse`). The DEFAULT stays strict RFC 8259, so the
rig's vector/manifest loading (`conformance-runner/src/loader.ts`, `request-diff.ts`)
keeps structural D6-rule-5 enforcement — a vector file containing `NaN` still refuses
to load.

Downstream consumers verified faithful for native non-finite numbers BEFORE the fix
was written: `pyTruthy` (`!== 0` → NaN/Infinity truthy = Python), `jsonDumpsLike`
(`String(NaN)` = `"NaN"` = `json.dumps`), `toPythonValue`/`pythonStr` (→
`pythonFloatStr` → `"nan"`/`"inf"`, message-text-only per R5.4), `isPlainRecord`
(number is not a record), the 403 truthy-scalar TypeError branch (bare `Infinity` body
now reaches the R10.7 bug-compat TypeError exactly as Python's truthy float does —
locked by a new test).

Tests (all written red-first): 5 in `lossless-json.test.ts` (constant/variant accept-
reject matrix incl. the strict default), 4 in `internals.test.ts` (200 NaN-object
success, 200 bare-NaN scalar return, 400 dict-shape + `error`-message preservation, 403
bare-`Infinity` TypeError), 1 in `app-request.test.ts` (422 dict shape + message).

## F2 (fidelity, minor) — Retry-After > 2^53−1 reads as ABSENT in TS

**Verdict: CONFIRMED → BLESSED as a sanctioned deviation** (playbook Discrepancy #6,
added this resolution). Reproduced: `backoff.ts` maps both `pythonInt` coded errors
(incl. `PY_INT_UNSAFE_INTEGER`) to null; CPython parses `int("9007199254740993")` fine.

Rationale for blessing rather than fixing: the R4.5 canonicalizer 2^53 policy means TS
has no faithful numeric representation of the raw value (returning a rounded double or
the 60 clamp would BOTH still diverge from Python's exact big int in the
`RateLimitError.retry_after` detail bag); the sleep path is behaviorally inert (Python
sleeps the 60s cap; TS takes the jittered exponential fallback ≤ 60s+jitter — sleep
durations are not vector-observable and Layer-3 injects the RNG); no corpus vector and
no Layer-3 assertion exercises a >2^53 header; the delta exists only for a header an
attacker must craft to be ≥ 285 million years. **The reviewers' shared complaint is
upheld**: the packet justification "no B0 consumer can produce one legitimately" is
WRONG for attacker-controlled headers — the corrected justification is the one above,
now recorded in the playbook discrepancy log, the `backoff.ts` JSDoc (citation updated
to Discrepancy #6 / this resolution), and the B0-notes decision-7 addendum. Re-examine
at the Phase-4 live gate only if a live 429 ever carries such a header (it cannot
plausibly; burn-in will show).

## F3 (fidelity, minor) + assertions Finding 2 — bare catch vs `except json.JSONDecodeError`

**Verdict: CONFIRMED → FIXED (reviewer split resolved toward the assertions lens).**
The fidelity lens proposed a comment; the assertions lens proposed the
`instanceof`-guard. The guard wins: it is strictly MORE faithful (Python's
RecursionError propagates past `except json.JSONDecodeError`; the analog RangeError now
propagates past the `LosslessJsonError` guard), it matches the in-repo `backoff.ts`
pattern for Python-builtin-exception ports, and it costs one line per site. Applied at
all three sites (`internals.ts` `parseBody` + tail re-parse, `app-request.ts` 422).
Locked by 3 new red-first tests (1M-deep `[` nesting → RangeError propagates on 2xx,
error-status, and 422 paths — never INVALID_RESPONSE / body-as-text). Note
`executeWithRetry`'s R2.10 filter already rethrows non-`MixpanelHttpError` values, so
the RangeError surfaces to the caller exactly as RecursionError does in Python.

## Assertions Finding 1 — `jsonl.test.ts` header miscites its Python source

**Verdict: CONFIRMED → FIXED.** `tests/unit/test_api_client.py::TestIterJsonlLines`
(:2709-2877, 8 tests) exists and drives `_iter_jsonl_lines` directly — I re-read it.
The header now cites it as a translation source with the reviewer's 8-behavior mapping
(no assertion was ever missing; this was an R10.2 audit-trail defect only).

## Assertions Observation A — `compat.cp_length` authored-vector budget (5 vs ≥10)

**Verdict: BLESSED — combined-bullet reading is the correct one.** The packet bullet
reads "`compat.cp_slice`/`compat.cp_length` (≥10: non-BMP at the cut point, negative
indices, start>end, empty)" — three of its four named case families (negative indices,
start>end, and the cut-point framing) do not exist for a length function, so a per-api
≥10 reading is incoherent for `cp_length`. Delivered coverage: cp_slice 11 + cp_length
5 = 16 combined, every named family present by id, plus 504 differential fuzz examples
against CPython `len()` at zero divergences (reproduced by both reviewers). Adding 5
filler vectors would force a full corpus re-pin cycle (P3-7) for no additional
behavioral lock. No action.

## Assertions Observations B/C/D + fidelity non-findings

- **B (jsonl.ts JSDoc `JSON.parse` example)**: APPLIED — caveat comment added steering
  B4-C2 to `parseLossless` (GATE-R5), keeping the Python-docstring illustration.
- **C (R6.7 AbortSignal seam hand-off)**: ACCEPTED — carried forward as a B4-C1 packet
  requirement (the B4 design-lite packet MUST state that signal-aware `request`/`sleep`
  closures satisfy R6.7 without touching B0 signatures). Noted in B0-notes addendum.
- **D (B4 hand-off list is load-bearing)**: ACCEPTED — the B4 gate must verify the
  B0-notes deviation-3 deferrals land (TestRetryStateResetRegression ×4, streaming
  project_id raise :1883-1891 / test_api_client.py:1567, negative-retry-after export
  case, form content-type, auth-header wire captures). Noted in B0-notes addendum.
- Fidelity non-findings (403 non-numeric project id, integral-float message rendering,
  commit-count process deviation, decision-13 entry-point substitutions): concur,
  accepted as recorded.

## No rulebook amendment filed

No fix pattern recurred ≥3 times (R10.4 threshold not met). The R2.5 jitter wording
amendment remains queued from playbook Discrepancy #1; F2's blessing adds Discrepancy
#6 rather than a rule change.

## Ripple check (post-fix)

- `npm run check` green (typecheck, eslint, prettier, vitest 73 files / 2,193 passed —
  300→313 in the client+compat suites, browser smoke OK).
- `npm run conformance`: **3,251 — 539 PASS / 0 FAIL / 2,712 UNPORTED @ b5c1369** —
  IDENTICAL to the pre-fix report (D6 rule 5 bars non-finite tokens from vectors and
  the strict default preserved rig loading, so no vector/harness record was
  invalidated; no corpus re-pin needed).
- `node throwaway/b0-2/run-edge-harness.mjs`: 47/47 (unchanged — harness untouched;
  the new coverage lives in the durable unit suites, and the gate task deletes
  `throwaway/` after this sign-off per P3-2c).
- Python repo: docs-only changes (this file, playbook Discrepancy #6, B0-notes
  addendum); `just check` re-run green.

## Commits

- TS repo (`main`): **629721b** — parser `pythonConstants` extension + 3-site
  flag/guard + jsonl header/JSDoc + backoff JSDoc citation + 13 tests.
- Python repo (`ts-port/phase2-contract-support`): this resolution + playbook
  Discrepancy #6 + B0-notes arbiter addendum.
