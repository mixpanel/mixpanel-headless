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
