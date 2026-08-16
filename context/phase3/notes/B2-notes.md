# B2 batch notes — validators (validation.py + user_validators.py)

Batch-level record per P3-2e item 5. Module-level records live in
`B2-M1-notes.md` / `B2-M2-notes.md` / `B2-M3-notes.md` / `B2-BIND-notes.md` /
`B2-HK-notes.md`; review artifacts in `context/phase3/design/`
(`b2-review-assertions.md`, `b2-review-fidelity.md`,
`b2-review-resolution.md`; review commits 61a64a0 / 996957d, arbiter
cc12030).

## What shipped (batch summary)

- **Scope**: `_internal/validation.py` (3,090 LOC) +
  `_internal/query/user_validators.py` (580 LOC) →
  `packages/core/src/query/{validation-shared,validation-args,
  validation-bookmark,schema-sorting,user-validators,...}.ts` (per the
  b2-packets.md V1a/V1b/V2 sharding), plus the deferred export
  `validate_bookmark` and the `bookmarks/enums.ts` `TODO(port)` closure
  (`_MAX_FUNNEL_STEPS`/`_MAX_HOLDING_CONSTANT`, landed in V1a per the
  packet's one-owner rule).
- **Vectors**: 690 replayable (`validation.` 512 + `user_validators.`
  178), all `kind: builder` with `expect.error` cases; all 690 PASS on
  the first replay at the B2-BIND commit (TS `2015565`) — full-corpus
  checkpoint at bind: 3,251 vectors — 1,229 PASS / 0 FAIL / 2,022
  UNPORTED @ corpus b5c1369.
- **Layer-3**: 693 translated tests green at the arbiter HEAD (M1 406 +
  M2/M3 remainder; R10.2 name-by-name diff verified clean by the
  assertions reviewer over all 10 source files).
- **Bindings/oracle**: 11 api names registered fable-side (B2-BIND,
  P3-2 b′) — 9 `validation.*` + 2 `user_validators.*`;
  `validate_sorting_block` bound despite zero vectors;
  `bookmark_schema.validate_with_pydantic` intentionally left to the B3
  binder (packet rule — B3 must pick it up).
- **Module commits (TS main)**: 5c0e032 (M1/V1a), 617da2b (M2/V1b),
  83fbe2d (M3/V2), 2015565 (BIND), 6c1e43f (arbiter fixes). Python
  side: strategies/locks/notes commits through cc12030.
- **New sanctioned deviations**: playbook Discrepancies #8
  (out-of-annotation scalars — boundary at the declared annotation) and
  #9 (S4 warning-order flip on integer-like unknown chart keys).
  R10.4 amendment filed: watchlist #13 (`isinstance(x, dict)`
  discrimination — import `isPythonDict`, never re-derive).

## Volume-tier observations (for the tiering record)

Tier history: **B2-M1 attempt 1 ran on Sonnet 4.5** by harness alias
mis-resolution, BEFORE the 2026-08-15 tiering revision (P3-3 revision
note: Sonnet removed from the program; volume tier pinned to Opus 5 via
`ANTHROPIC_DEFAULT_OPUS_MODEL`). That attempt was harness-killed
mid-flight; attempt 2 (opus) kept ~1,300 LOC of its work after
line-by-line re-verification and discarded its non-R10.2 test file
(record in B2-M1-notes.md). M2/M3/arbiter-era work all ran on the
pinned Opus 5; all rig/review/binding tasks ran fable per P3-3.

Review-finding tier attribution (8 findings + 3 observations across the
pair, verdicts in b2-review-resolution.md):

- **Tier-attributable module/test defects (3)**: F1 blocker
  (isDict/isPlainObject dict conflation, 11+4 oracle-confirmed shapes,
  recurred 4× → the watchlist #13 amendment; incl. the arbiter F1b
  extension), F3 major (CM5 spelled `typeof !== "number"` instead of
  the `instanceof CohortDefinition` isinstance twin), ASSERT-F1 minor
  (M1 PBT Hypothesis-Unicode strategies ASCII-narrowed without header
  citations). All three are Python-semantics-fidelity misses in
  opus-authored code/tests that the fable review pair caught — the
  P3-3 "review never downgrades" rule earning its keep.
- **Blessed platform/boundary classes, NOT tier-attributable (2)**: F2
  (out-of-annotation scalars → Discrepancy #8; the TS compiler polices
  what CPython leaves to runtime raises) and F4 (S4 order flip →
  Discrepancy #9; JS integer-like key ordering is a platform property
  any tier hits).
- **Clerical (3)**: ASSERT-F2 (test header count typo), F5 (stale
  throwaway RUN.md prose), + the assertions reviewer's 2 nits (header
  class-count typo; packet 5-vs-4 edge-case count).
- Additionally two REAL defects were found pre-review by the B2-BIND
  fuzz (fable stage): the GroupBy codec carrier crash (rig codec —
  fable-owned, not a module defect) and the requireHashable
  frozenset-membership divergence (module-shipped total-function
  spelling that M2 had itself flagged for R10.7 adjudication —
  deliberate and flagged, so only weakly tier-attributable).

Net: 690/690 vectors and the full translated Layer-3 suite were green
BEFORE review on opus-authored work; the defects that survived to
review were concentrated in Python-runtime-semantics discrimination
(dict-ness, isinstance twins, Unicode strategy breadth) — consistent
with the B2 packet's watchlist predictions and now partially
mechanized (watchlist #13, R11.7).

## B2 gate (P3-2 step e) — attempt 1, 2026-08-15

**RESULT: GATE BLOCKED at step (4)** — the seed-52794688 replay of the
differential full-suite regression found ONE real divergence (a
conformance-rig codec regression introduced by the B2-BIND TS commit
`2015565`; repro committed). Steps (1)–(3) and (5) all passed; the gate
COMMITS were deliberately not performed (B0 attempt-1 precedent: the
batch-status flip, the report-JSON archive under
`context/phase3/reports/`, and the throwaway removal belong to the
passing gate run — the TS working-tree flip was reverted, leaving TS
main clean at 6c1e43f).

### Gate step results

- [x] (1) batch-status flip — EXECUTED AND VERIFIED, THEN REVERTED
  (pending the passing run). With `validation.` + `user_validators.`
  flipped to `done`: batch-status unit suite 13/13 green (incl. a new
  flip-state test and the full-corpus prefix-coverage checks).
  Standing no-prefix-collision assertion (P3-5 rule 4) run mechanically
  over all corpus api names: exactly 10 distinct names match the two
  prefixes (8 `validation.*` + 2 `user_validators.*`), all of them
  B2-registered names — no pending name of any other batch is captured
  (plus the vectorless `validation.validate_sorting_block`, bound at
  B2-BIND). Per-prefix corpus re-measure sums to exactly 3,251;
  `validation.` carries 512 vectors and `user_validators.` 178 (= the
  P3-1 row's 690).
- [x] (2) conformance checkpoint — COUNTS MATCH (recorded here, archive
  withheld until the gate closes). `npm run conformance` @ TS 6c1e43f +
  the flip, corpus b5c1369: **3,251 vectors — 1,229 PASS / 0 FAIL /
  2,022 UNPORTED** — exactly the dagger-adjusted expectation 539 + 690.
  Dagger-footnote verification: ZERO of the 690 B2 vectors carry any
  `call.setup[]` entry (mechanical scan), and no vector of any other
  prefix carries a `validation.*`/`user_validators.*` setup api — the
  B2 gate delta equals the raw vector count (690) with no cross-batch
  setup carry-over, as the P3-1 † footnote implies for B2.
- [x] (3) oracle probes (GF4) — PASS. One `oracle.call` per newly
  registered api on BOTH bridges (probe = the family's first edge call
  for each api from `PHASE3_B2_TARGETS`): **11/11 non-"unknown api"
  call-DATA responses, canonicalized outputs pairwise equal**
  (`validation.validate_{time,group_by,query,funnel,retention,flow}_args`,
  `validation.validate_bookmark`, `validation.validate_flow_bookmark`,
  `validation.validate_sorting_block`,
  `user_validators.validate_user_{args,params}`). Bridge identities:
  oracle-py 0.2.1 / oracle-ts 0.0.0, both @ source_commit b5c1369,
  protocol 1.1.
- [x] (4) differential full-suite regression — **FAIL (1 real
  divergence)**. Three seeded runs over all 33 `ALL_TARGETS` families
  (cumulative surface), P2-9 budget ≥500/family:
  - fresh seed **21091621**: 17,163 examples / 2,539 explained skips /
    **0 divergences**;
  - B0-gate seed **28631260**: 17,163 examples / 2,539 explained skips /
    **0 divergences**;
  - B0-gate seed **52794688**: 16,770 examples / 2,539 explained skips /
    **1 divergence** — `codec.roundtrip` on
    `GroupBy(bucket_size=18.0)`: Python preserves the `$type: float`
    carrier, TS re-encodes plain `18` (float-ness lost). Root cause:
    the `2015565` GroupBy-codec fix unwrapped carriers at decode
    without the SignedReplay-precedent encode-side re-tag; the
    unconditional re-tag is also wrong here because Python's buckets
    are `int | float | None` — the remediation needs decode-time
    float-ness memory. Full triage + remedy sketch:
    `conformance/differential/oracle/RUN.md` (B2 attempt-1 entry);
    repro `conformance/differential/repros/2026-08-16-codec-roundtrip.json`
    (BLOCKS the gate while present). Rig-owned (fable) defect — library
    code and all 690 B2 vectors are unaffected.
  - Skip ledger: 2,539 = the five B3-pending Phase-1 families only;
    `validators_by_code` now runs both-bridge (510 examples, 0 skips),
    un-skipped by the B2 registration exactly as B2-BIND predicted.
- [x] (5) referees — NOT REQUIRED at B2, per P3-7: referees (a)+(b) run
  at the B3 and B6 gates (the bookmark-touching batches). B2 validates
  bookmark PAYLOADS but constructs none (validators emit
  `{path, code, severity}` triples only). Stated for the record.
- [ ] (6) throwaway/b2-* cleanup + eslint/prettierignore
  throwaway-glob revert — DEFERRED to the passing gate run (arbiter
  sign-off @ cc12030 permits it, but the m1/m2/m3 harnesses are the
  re-run drivers the remediation verification needs; B0 attempt-1
  precedent).
- [x] (7) checks at final HEADs — TS main left clean at 6c1e43f
  (`npm run check` green there per the arbiter record; no TS commit
  this attempt); `just check` green on the Python support branch at the
  attempt-1 record commit.

### Recommended unblock path

1. Fable-tier rig remediation on TS main: GroupBy codec float-ness
   memory (decode records which bucket fields arrived as float
   carriers; encode re-tags exactly those via `pythonFloatStr` — the
   `signedReplayCodec` shape with a WeakMap or a custom tag codec),
   red-first lock in `conformance-runner/test/codecs.test.ts` covering
   BOTH directions (int bucket stays `18`, float bucket stays
   `{"$type":"float","value":"18.0"}`), then `codec_roundtrip` re-runs
   at seeds 52794688 / 21091621 / 28631260 (all must be clean) + a
   review pass per P3-2d norms for a rig-codec touch.
2. Delete `repros/2026-08-16-codec-roundtrip.json` after the green
   re-run (repros block while present).
3. Re-run this gate from step (4) (fresh seed again), then perform the
   flip commit (step 1), the report archive (step 2), cleanup (step 6),
   and the gate commits (TS gate commit on main + Python docs/report
   commit).
4. Standing-posture note for the arbiter/P3-7: a rig-codec change must
   re-run `codec_roundtrip` before its task closes — both
   post-`2015565` fuzz runs were `--targets`-restricted to the 11 B2
   families, so the regression sat invisible until this gate.

## B2 gate (P3-2 step e) — attempt 2, 2026-08-15: **GATE CLOSED**

**RESULT: PASS.** The attempt-1 unblock path was executed verbatim;
every gate step re-verified clean at the remediation HEAD.

### Remediation (unblock path steps 1–2)

- TS commit `ad830fb` (fable, rig code): GroupBy moved out of the
  generic `DATACLASS_CODECS` table into a dedicated `groupByCodec` —
  decode reuses the generic half verbatim (unknown-field rejection,
  required check, carrier unwrap; behavior unchanged from `2015565`)
  but RECORDS which of the three bucket fields arrived float-spelled in
  a module-level `WeakMap` (`GROUP_BY_FLOAT_BUCKETS` — GC'd with the
  instance, invisible to library consumers); a custom encode re-tags
  exactly the remembered fields as
  `{$type: "float", value: pythonFloatStr(v)}` under the same
  integral-finite guard as Python `_encode_common`'s rich-payload
  tagging. Int buckets stay raw (`int | float | None`,
  `types.py:8367-8373`); directly-constructed instances (no memory)
  keep the generic declared-field walk — matching Python, where a
  library-built `GroupBy(bucket_size=18)` encodes `18`.
- Red-first locks: `conformance-runner/test/codecs.test.ts` +4 tests
  (float carrier stays carrier, plain int stays int, mixed per-field,
  direct-construction raw) — the two carrier tests were RED against
  `6c1e43f`, green after the fix.
- Single-family `codec_roundtrip` re-runs: seeds **52794688 /
  21091621 / 28631260** — 512 examples / 0 skips / 0 divergences each.
- Repro `repros/2026-08-16-codec-roundtrip.json` deleted (resolved).
- Review pass for the rig-codec touch (P3-2d norms, self-executed at
  the gate tier — fable): decode behavior diffed unchanged vs
  `2015565`; encode diffed line-by-line against Python
  `_encode_common` (`record/codecs.py:219-222` — carrier iff
  `in_rich_payload and checked.is_integer()`; the re-tag spelling
  `pythonFloatStr(v)` reproduces the PyFloat carrier's
  canonical-validated spelling byte-for-byte); dispatch uniqueness
  confirmed (single `"GroupBy"` key in `CONTRACT_TAG_CODECS`,
  `instanceof` matcher); sweep re-confirmed no other decode-side
  unwrap lacks its encode twin (`signed_at` has both halves;
  `codec-sweep` suite green).

### Gate step results (attempt 2)

- [x] (1) batch-status flip — EXECUTED AND COMMITTED (TS gate commit):
  `validation.` + `user_validators.` → `done`; header comment moved to
  the done list (+ Discrepancy-#2 note for the B3-owned
  user_builders/expressions/transforms prefixes). Batch-status suite
  **13/13** green (incl. the new B2 flip-state test asserting both
  flips AND that the B3 prefixes stay pending). Standing
  no-prefix-collision assertion re-run mechanically over all corpus
  api names: exactly **10** distinct names match the two prefixes
  (8 `validation.*` + 2 `user_validators.*`), all B2-registered (the
  11th registered name, `validation.validate_sorting_block`, is
  vectorless); per-prefix re-measure: `validation.` **512** +
  `user_validators.` **178** = **690**, corpus total exactly **3,251**.
- [x] (2) conformance checkpoint — COUNTS MATCH: `npm run conformance`
  with the flip @ corpus b5c1369: **3,251 vectors — 1,229 PASS /
  0 FAIL / 2,022 UNPORTED** (= 539 + 690, the dagger-adjusted P3-1
  expectation). Dagger re-verified: all 690 B2 vectors carry
  `call.setup[]` length 0, and zero foreign vectors carry a
  `validation.*`/`user_validators.*` setup api — gate delta = raw 690.
  Report archived: `context/phase3/reports/2026-08-15-b2-gate.json`.
- [x] (3) oracle probes (GF4) — PASS at the remediation HEAD: 11/11
  apis answer call DATA on BOTH bridges, canonical outcomes pairwise
  equal (first `PHASE3_B2_TARGETS` edge call per api; oracle-py 0.2.1 /
  oracle-ts 0.0.0, both @ b5c1369, protocol 1.1).
- [x] (4) differential full-suite regression — **ALL CLEAN**. Three
  seeded runs over all 33 `ALL_TARGETS` families, P2-9 budget:
  - fresh seed **3343231**: 17,163 examples / 2,539 explained skips /
    **0 divergences**;
  - B0-gate seed **28631260**: 17,163 / 2,539 / **0**;
  - B0-gate seed **52794688** (attempt 1's diverging seed): 17,163 /
    2,539 / **0** — `codec_roundtrip` runs its full 512.
  - Skip ledger unchanged: 2,539 = the five B3-pending Phase-1
    families; every both-bridge family ≥ 504 examples. Raw JSONs:
    `2026-08-15-b2-gate-attempt2-seed{3343231,28631260,52794688}*.json`.
- [x] (5) referees — NOT REQUIRED at B2 per P3-7 (referees (a)+(b) run
  at the B3 and B6 gates, the bookmark-touching batches; B2 validates
  bookmark payloads but constructs none). Stated for the record.
- [x] (6) cleanup — `throwaway/b2-m1` / `b2-m2` / `b2-m3` removed after
  arbiter sign-off (cc12030), plus the B2-era throwaway entries in
  `eslint.config.js` (ignore glob + mjs-globals block), `.gitignore`,
  and `.prettierignore` (B0-gate 8f79b67 precedent).
- [x] (7) checks at final HEADs — `npm run check` green on TS main at
  the gate HEAD `794fea1` (3,624 passed / 2,022 corpus-skipped;
  remediation `ad830fb` beneath it); `just check` green on the Python
  support branch at the gate docs/report commit.

### Standing-posture rule adopted (P3-7 addendum, from the attempt-1
process note)

Any change to rig codec code (`vector-codecs.ts`, runner `codecs.ts`,
canonicalizers) re-runs `codec_roundtrip` (at minimum) before its task
closes — never waits for the next batch gate. Recorded in
`conformance/differential/oracle/RUN.md` alongside the attempt-2 run
record.
