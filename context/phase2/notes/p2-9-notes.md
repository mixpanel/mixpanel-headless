# P2-9 running notes — differential gate

## Ground survey (done)
- Python branch ts-port/phase2-contract-support @ a7b8dfc; TS main @ d911a6f. P2-1..P2-8 complete.
- Oracle protocol 1.0: conformance/schema/oracle-protocol.md; oracle-py server.py; oracle-ts differential/oracle/server.ts (compat-only surface).
- Fuzz harness: conformance/differential/fuzz_harness.py (Phase-1, 7 targets); strategies.py imports tests.test_user_query_pbt.filter_strategy.
- All 81 Phase-2 guard codes (C7 families CF CB CA CM CD TC MT FM LC FD LG GB EV FB FF EX HC FS UA + C6-d RS SR RE RP RB) have corpus types.* vectors -> edge harvest from corpus is complete by construction.
- 44 distinct types.* apis in api-index (matches design).
- oracle-py `_invoke` uses target(**decoded) — MISSES `_bind_variadic` (needed for types.Filter.list_contains, types.CohortDefinition{,.all_of,.any_of}). Must fix on support branch.
- oracle-ts: needs (a) types.* surface via conformance-runner bindings module (createRunnerDeps reuse), (b) codec.roundtrip method, (c) protocol 1.1.
- npm run oracle = node scripts/run-oracle.mjs (esbuild bundle at runtime).

## Work plan
1. [x] Survey
2. [x] Protocol addendum 1.1 (codec.roundtrip) in oracle-protocol.md (§8; -32601 row; version line)
3. [x] oracle-py: codec.roundtrip + _bind_variadic fix + tests (29 pass)
4. [x] oracle-ts: createRunnerDeps reuse (44 types.* live), codec.roundtrip, PROTOCOL 1.1, expect/input encoding transforms, oracle-only replay codecs + tests (48 pass)
5. [x] strategies.py: 8 Phase-2 targets + corpus guard-edge harvest (81 codes + 44 apis, deterministic)
6. [x] harness: codec.roundtrip sentinel routing in OracleProcess.call; ALL_TARGETS
7. [x] edge-set coverage artifact (conformance/differential/phase2-edge-coverage.json, sync test)
8. [x] Fuzz run >=500/family vs oracle-ts: status ok, 4,151 examples, 0 skips, 0 divergences
       (phase2-gate.json); full 15-target regression at 200: ok, 3,217 examples, 0 divergences
       (Phase-1 non-compat targets skip UNPORTED as before)
9. [x] Python checks: ruff check/format clean, mypy 52 files clean, 406 conformance tests,
       3,179-vector Python runner green, interrogate 100% (+ full just check, see below)
10. [x] TS npm run check EXIT=0 (62 files, 1,880 passed / 2,718 skipped); conformance CLI:
        3,179 vectors — 461 PASS (419 types.* + 42 gate), 0 fail @ corpus 8ae76314

## Real library findings (both FIXED in the TS commit, repros committed)
4. `CohortCriteria.hasProperty` unknown operator: Python raises bare KeyError (uncoded, R5.5);
   TS silently constructed with an undefined selector operator. Fix: file-local KeyError mirror
   in cohort.ts AFTER the CD7 guard (Python check order) + translated tests. Repro:
   conformance/differential/repros/2026-08-15-types-CohortCriteria-has_property-keyerror.json
   (right side captured by replaying the probe against the pre-fix oracle via git stash).
5. `Filter.inCohort/notInCohort` with an inline CohortDefinition: leftover P2-5a stub
   `throw new Error('TODO(port, P2-5b)...')` — P2-5b never closed it (no recorded vector reaches
   the branch). Fix: buildCohortFilter embeds sanitizeRawCohort(cohort.toDict()) per Python
   `_build_cohort_filter` + translated tests. Repro:
   conformance/differential/repros/2026-08-15-types-Filter-in_cohort.json

## Triage log (divergences found during bring-up, all FIXED before the gate run)
1. Rich `$type` in TS oracle.call outputs (Filter.in_cohort, Metric, CohortBreakdown, Exclusion repros):
   oracle-py `_encode_result` uses the EXPECT encoding (no rich tags); TS bindings encode input-tagged.
   Fix: `toExpectEncoding` transform in oracle-ts (strip rich tags; built-ins stay). Latent because
   constructor SUCCESS outputs were never recorded (all 389 constructor vectors are guard-error cases).
2. Integral-float fidelity (Filter.in_the_last / has_property / FrequencyFilter / roundtrip 18.0 repros):
   raw token 18.0 loses float-ness through TS decodeInputKwargs (18), Python keeps float.
   Fix: `tagIntegralFloatTokens` pre-decode (-> PyFloat), float-tag -> raw-token conversion on the
   output side (expect encoding: floats raw everywhere; input encoding: raw only in plain positions —
   measured against encode_input_value/encode_expect_value).
3. ReplayBundle success output unencodable on TS (UnencodableValueError repro): ReplaySummary/
   ReplayEvent/ReplayBundle deliberately unregistered in vector-codecs (P2-8 sweep tag-exercise
   honesty). Fix: oracle-only codec rows registered on the oracle's own registry instance
   (`registerOracleReplayCodecs`) — sweep untouched.
All six repro files deleted after fixes verified (20-example full-family smoke: 311 probes, 0 divergences).

## Decisions
- codec.roundtrip = 4th protocol METHOD (not an oracle.call api). params {value} -> {ok:true, output: encode(decode(value))}. Decode failure -32602; encode/canonicalization failure -32000. PROTOCOL_VERSION bumped to "1.1" both sides.
- Python roundtrip: decode_value + encode_input_value ($type-tagged form). TS: codecs.decodeValue + codecs.encodeValue over createRunnerDeps codec registry.
- Harness: FuzzCall api sentinel "codec.roundtrip" with kwargs {"value": x}; OracleProcess.call special-cases it into the codec.roundtrip method.
- Strategies: loose (valid + guard-tripping) draws are GOOD — outcome parity includes error {class,code}. Edge sets = R10.9 items + one harvested corpus probe per Phase-2 guard code (decode_input_kwargs on the recorded vector input).
- Family grouping (8): filter(13 apis), metric_group(6), cohort(13), funnel(3), retention_flow(2), frequency(2), replays(6), codec_roundtrip(1 method). 44 apis total + roundtrip.
