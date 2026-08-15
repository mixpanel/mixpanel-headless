# B2-HK — B0 follow-up obligations (running notes, R10.13)

Status: COMPLETE (pending final `just check` + commit at write time). Gate items:
- [x] (1) R10.4 rulebook amendment R11.7 [SA3] (trim/int pattern, 13x at B0 gate) —
      appended to rulebook §11, cites 3c07d4e + 2026-08-15-b0-gate.json, carries the
      rig-internal exemption and the third-parser (pydantic-core) carve-out.
- [x] (2) Spot-review TS 3c07d4e (P3-2d checklist) — VERDICT GO; safeInt >2^53-1 ->
      default_ BLESSED as playbook Discrepancy #7 (R4.5). Record below + B0-notes addendum.
- [x] (3) Rig fix: emit.py canonical_json escapes U+0085/U+2028/U+2029 (\uXXXX);
      3 TDD-red-first tests in conformance/tests/test_emit.py (unit escape, byte-identity
      drift lock, end-to-end splitlines framing); committed corpus scanned: 0 raw hazard
      hits in 175 files => byte-no-op on every committed bundle, D8 drift clean by
      construction (no re-extraction needed; the full record-mode drift re-run stays
      CI-only per the justfile).
- [x] (4) Bug report filed: context/phase3/bug-reports/python-handle-response-403-typeerror.md
      (live-reproduced matrix incl. the TypeError crash and the list element-membership
      quirk; R10.7 fix choreography documented).
- [x] just check green (7,116 unit tests passed / coverage 92.33% / conformance suites
      517 + 3,251-vector Python replay all green); local commit on
      ts-port/phase2-contract-support.

## Scope note (deliberate non-changes)
- harvest_storybook.py still writes bundles with plain ensure_ascii=False json.dumps —
  same hazard class, out of this packet's scope (task named emit.py); flagged in the
  B0-notes addendum for the next touch of that tool.
- No TS-repo commit: the spot-review found nothing to fix on TS main; verdict +
  blessing recorded Python-side (playbook Discrepancy #7, B0-notes addendum, this file).

## (2) Spot-review 3c07d4e — VERIFIED, verdict GO (details for final record below)
- R10.2: additive-only — numstat shows 0 deletions in both test files (strip-guards.test.ts
  +223/-0 new; flow-query-result.test.ts +37/-0 appended describe); existing suites untouched.
- 62 tests (15 strip-guards + 47 flow-query-result incl. the 7 new safeInt) green at TS HEAD 8f79b67.
- Guard order EV1-before-EV2: TS guards.ts:87-99 strip-emptiness precedes CONTROL_CHAR_RE;
  Python types.py:9116-9125 identical order; probe RetentionEvent("\x1c") -> EV1 on CPython.
- CPython probes: 22/22 reproduce (/tmp/b2hk_probe.py — strip blankness both directions,
  int(str) grammar incl. underscores/Nd/U+0085+NBSP surround/FEFF+1C-1F rejects, big-int exact,
  _safe_int library-level, RetentionEvent EV1/FEFF-accept).
- All 13 cited Python .strip() sites confirmed (types.py 9116,9153,7129,10162,8309,8231,
  8707,8720,8953,8392,9532,9644,4921).
- Residual grep: zero bare .trim() emptiness guards left in packages/core/src/types/;
  compat-internal trims exempt (python-float.ts:79 post-normalization); OBSERVATION:
  coerce.ts:133,167 use .trim() but their Python twin is pydantic-core lax coercion (a THIRD
  whitespace set — Rust trim: no FEFF, no 1C-1F), not int(str)/str.strip(); FEFF-prefixed
  numeric strings are a potential divergence direction there — flag for the review pair of
  whichever batch first consumes coerce.ts paths in vectors (not part of the 3c07d4e class).
- safeInt >2^53-1 -> default_: BLESSED per R4.5 (Discrepancy #7 filed in playbook). Python
  _safe_int (types.py:10548-10583) returns the exact big int via int(str); consumers are flow
  result counts (totalCount fields) — a count beyond 2^53 is not producible by real responses,
  R4.5 leaves no faithful TS number, throwing would break _safe_int's total-function contract
  (Python never raises there), and the pre-fix parseInt path returned an IMPRECISE number
  (strictly worse). Not vector/fuzz-observable today (no oracle family drives _safe_int).
  Re-examine only if a flows response ever carries such a count (Phase-4 burn-in).

## Findings so far
- emit.py hazard confirmed by reading: `canonical_json` (emit.py:235) uses
  `ensure_ascii=False`; json.dumps escapes only <0x20 controls, so U+0085/U+2028/U+2029
  are emitted RAW inside string literals; bundle framing is "\n".join(lines) and any
  splitlines()-based reader splits mid-vector. splitlines set minus \n\r minus <0x20
  (already escaped) = exactly {U+0085, U+2028, U+2029} — the surgical escape set.
- Fix plan (read-compatible, drift-safe): post-process json.dumps output in
  canonical_json, replacing raw U+0085/U+2028/U+2029 with their \uXXXX escapes.
  These cps can only occur inside JSON string literals, so the textual replace is
  value-preserving; bundles without those cps are byte-identical (drift clean).
  Must verify committed corpus carries none of the raw cps.
