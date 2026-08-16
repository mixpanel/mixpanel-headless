# Differential full-suite regression RUN records (playbook P3-7)

One entry per batch-gate regression run (oracle-py <-> oracle-ts over the
cumulative registered surface, fresh seeds, P2-9 budget >=500 examples per
api family + the R10.9 edge sets riding as `@example` decorators).

---

## 2026-08-15 — B0 gate, attempt 1: **DIVERGENCE — GATE FAIL**

- Command (re-runnable; reproduces exactly — seeded generation):

  ```bash
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 52794688 --report json
  ```

- Harness: `--seed` mode added this gate (fresh-yet-reproducible seeded
  generation, `derandomize=False` + `hypothesis.seed`; `seed=None` keeps the
  historical derandomized behavior — locked by
  `conformance/tests/test_fuzz_harness.py::TestSeededRuns`).
- Bridges: oracle-py @ ts-port/phase2-contract-support (post-a501829 tree),
  oracle-ts @ main 629721b, corpus pin b5c1369.
- Targets: all 22 registered (`ALL_TARGETS` = Phase 1 + Phase 2 + Phase 3 B0).
- Totals: **11,294 examples, 3,049 skips, 1 divergence** → exit 1, status
  `divergence`.
- Skips (all explained, protocol §4.2 UNPORTED-from-either-side): the six
  Phase-1 pure-function families whose apis are still pending on oracle-ts —
  `build_filter_entry` 508, `build_segfilter_entry` 508, `filter_to_selector`
  508, `filters_to_selector` 510, `normalize_on_expression` 505,
  `validators_by_code` 510 (B2/B3 modules; cross-language coverage begins at
  their batch gates). Every both-bridge family ran >=500 with 0 skips:
  codec_roundtrip 512, cohort_family 533, filter_family 529, frequency_family
  515, funnel_family 508, metric_group_family 523, replay_family 524,
  retention_flow_family 520, pythoncompat 517, python_int 513, python_float
  514, python_strip 507, sorted_strings 507, cp_length 504, cp_slice 508,
  jsonl_chunks 511.
- **Divergence (REAL — TS library bug, Phase-2 types layer)**:
  `types.RetentionEvent(event="")` (U+0085 NEL, the sole character) →
  Python raises `ParamValidationError` `EV1_EMPTY_EVENT`; TS constructs
  successfully. Shrunken repro:
  `conformance/differential/repros/2026-08-15-types-RetentionEvent.json`
  (BLOCKS the gate while present, playbook P3-2c/P3-7).
- Triage (root cause verified in both sources): Python
  `types.py::_validate_event_name` tests `not event.strip()` (CPython
  `str.strip()` whitespace set — 29 cps incl. U+001C–U+001F and U+0085 NEL);
  TS `packages/core/src/types/query-params/guards.ts:82` `validateEventName`
  tests `!event.trim()` (ECMAScript WhiteSpace+LineTerminator — does NOT
  strip U+001C–U+001F/U+0085, DOES strip U+FEFF). Divergent input classes for
  every trim-based emptiness guard: strings of only {U+001C..U+001F, U+0085}
  (TS accepts / Python rejects) and {U+FEFF}-only strings (TS rejects /
  Python accepts — inverse direction, probed manually). The B0-1
  `pythonStrip` (`packages/core/src/compat/python-strip.ts`, pinned
  whitespace.gen.ts) is the mechanical remedy. Remediation scope (grep
  inventory, ~24 sites): `types/query-params/guards.ts` (event + name
  guards), `filter.ts:219,1187`, `funnel.ts:179`, `group-by.ts:86`,
  `frequency.ts:87,193`, `metric.ts:171`, `cohort.ts:379,397,633`,
  `types/entities/data-governance.ts:214`, plus a case-by-case look at
  `types/results/query-engine.ts:62` (`parseInt(value.trim())` — numeric
  parse, different semantics). Fix is TS-only (Python is the arbiter and is
  correct → NOT an R10.7 event, no corpus re-pin); it must land as a
  fable-tier remediation task with red-first tests + retention_flow_family
  (and sibling family) fuzz re-runs, then the B0 gate re-runs from step (4).
- Why Phase 2 missed it: P2-9 ran derandomized (seedless) — its fixed
  generation never emitted a {U+001C–1F, U+0085}-only string for these
  families; the corpus carries no such vector (D6-safe cps, just never
  recorded). First fresh-seed run caught it — the P3-7 fresh-seeds mandate
  doing exactly its job.

---

## 2026-08-15 — B0 gate, attempt 2: **CLEAN — GATE PASS**

- Remediation between attempts (TS main `3c07d4e`, fable-tier, red-first):
  all 13 trim-based emptiness guards in `packages/core/src/types/**`
  replaced with `pythonStrip` (both divergence directions covered:
  {U+001C..U+001F, U+0085}-only now rejected, U+FEFF-only now accepted;
  guard order locked — strip-emptiness precedes the control-char check,
  so U+001C-only events raise EV1, matching Python), and `safeInt`'s
  `\s`-regex + `parseInt` string branch replaced with `pythonInt`
  (guarded catch, F3/A2 pattern). Every test expectation CPython-probed.
  `safeInt` >2^53−1 maps to `default_` (R4.5; playbook Discrepancy #6
  pattern — CPython returns the exact big int; the old `parseInt` path
  returned an imprecise number) — flagged in B0-notes for the next
  review cycle. 15 new guard tests (`strip-guards.test.ts`) + 7 safeInt
  grammar tests; 20 red before the fix, all green after.
- Commands (re-runnable; both reproduce):

  ```bash
  # step-(4) fresh-seed run (gate of record):
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 28631260 --report json
  # attempt-1 recorded-seed verification (the divergent generation, now clean):
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 52794688 --report json
  ```

- Bridges: oracle-py @ ts-port/phase2-contract-support (post-493322f tree),
  oracle-ts @ main 3c07d4e (identical results at gate HEAD 8f79b67 — the
  gate commit touches no library code), corpus pin b5c1369.
- Targets: all 22 registered (`ALL_TARGETS`, cumulative through B0).
- Totals, BOTH runs: **11,281 examples, 3,049 skips, 0 divergences** →
  exit 0, status `ok`. (Attempt 1's 11,294 = 11,281 + 13 shrink-phase
  extras from the divergence; per-family example counts are
  seed-independent — budget + `@example` edge decorators.)
- Skips (all explained, protocol §4.2, same six B2/B3-pending Phase-1
  families as attempt 1): `build_filter_entry` 508,
  `build_segfilter_entry` 508, `filter_to_selector` 508,
  `filters_to_selector` 510, `normalize_on_expression` 505,
  `validators_by_code` 510.
- Raw harness JSON: `2026-08-15-b0-gate-attempt2.json` (fresh seed
  28631260) + `2026-08-15-b0-gate-attempt2-seed52794688-verify.json`.
- Repro `repros/2026-08-15-types-RetentionEvent.json` DELETED (resolved
  by the remediation; single-family re-run at its recorded seed is
  clean). The two remaining `repros/2026-08-15-types-*` files are
  RESOLVED P2-9 triage records (bugs fixed in Phase 2; the P2-9 gate and
  the B0 attempt-1 gate steps both closed with them present) — they do
  not block.

---

## 2026-08-15 — B2 gate, attempt 1: **DIVERGENCE — GATE BLOCKED**

- Commands (re-runnable; all three seeded runs reproduce exactly):

  ```bash
  # step-(4) fresh-seed run (clean):
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 21091621 --report json
  # B0-gate seed replays (28631260 clean; 52794688 DIVERGES):
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 28631260 --report json
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 52794688 --report json
  ```

- Bridges: oracle-py @ ts-port/phase2-contract-support (post-cc12030
  tree), oracle-ts @ main 6c1e43f (the B2 arbiter-fix HEAD), corpus pin
  b5c1369.
- Targets: all **33** registered (`ALL_TARGETS`, cumulative through B2 —
  the 22 B0-gate families + the 11 `PHASE3_B2_TARGETS`).
- Totals:
  - fresh seed **21091621**: **17,163 examples, 2,539 skips, 0
    divergences** → status `ok`;
  - seed **28631260** replay: **17,163 examples, 2,539 skips, 0
    divergences** → status `ok`;
  - seed **52794688** replay: **16,770 examples, 2,539 skips, 1
    divergence** (`codec_roundtrip` stopped at 119 examples on the
    shrunken repro) → exit 1, status `divergence`.
- Skips (all explained, protocol §4.2, identical across all three runs —
  2,539 = the five B3-pending Phase-1 families): `build_filter_entry`
  508, `build_segfilter_entry` 508, `filter_to_selector` 508,
  `filters_to_selector` 510, `normalize_on_expression` 505.
  `validators_by_code` (510 skips at the B0 gate) now runs both-bridge
  with 0 skips — the B2-BIND registration un-skipped it as predicted in
  `context/phase3/notes/B2-BIND-notes.md`. Every both-bridge family ran
  >= 504 examples (>= the P2-9 500 budget) except the divergence-stopped
  `codec_roundtrip` in the 52794688 run.
- Raw harness JSON: `2026-08-15-b2-gate-attempt1-seed21091621.json` +
  `2026-08-15-b2-gate-attempt1-seed28631260-verify.json` +
  `2026-08-15-b2-gate-attempt1-seed52794688-verify.json`.
- **Divergence (REAL — conformance-rig codec regression, introduced by
  the B2-BIND rig fix in TS commit `2015565`)**: `codec.roundtrip` of
  `GroupBy(property="plan", property_type="string", bucket_size=18.0)`
  (input `bucket_size` rides as the PyFloat carrier
  `{"$type": "float", "value": "18.0"}`). Python round-trips the float —
  re-encode yields the identical `$type: float` spelling; TS re-encodes
  `bucket_size` as plain `18` (float-ness lost). Shrunken repro:
  `conformance/differential/repros/2026-08-16-codec-roundtrip.json`
  (harness UTC date stamp; BLOCKS the gate while present, P3-2c/P3-7).
- Triage (root cause verified in both sources):
  - `2015565` fixed the V18 ctor-guard carrier crash by unwrapping the
    three GroupBy bucket fields (`bucket_size`/`bucket_min`/`bucket_max`)
    to native numbers at the codec `construct`
    (`packages/core/src/types/vector-codecs.ts:414-437`) — but ported
    only HALF of its own cited precedent: the `SignedReplay` `signed_at`
    codec pairs the decode-side unwrap with an ENCODE-side re-tag
    (`{$type: "float", value: pythonFloatStr(v)}` for integral values,
    vector-codecs.ts:640-645). GroupBy kept the generic dataclass encode,
    so a decoded float-carrier bucket re-encodes as a bare JSON integer.
  - The SignedReplay-style unconditional integral re-tag is NOT the
    right fix here: Python's `GroupBy` buckets are annotated
    `int | float | None` (`types.py:8367-8373`), so `bucket_size=18`
    (int) must re-encode as `18` while `18.0` (float) must re-encode as
    the carrier — the TS instance's plain `number` cannot carry that
    distinction by itself. Remedy sketch for the remediation task
    (fable, rig code): remember float-ness at decode (e.g. a codec-module
    WeakMap from the constructed `GroupBy` to the set of float-spelled
    bucket fields, consulted by a custom encode; or a custom tag codec
    like `signedReplayCodec` with the same memory), red-first lock in
    `conformance-runner/test/codecs.test.ts` (roundtrip both directions:
    int stays int, float stays float), then re-run `codec_roundtrip` at
    seed 52794688 (must go clean) plus the other two gate seeds.
  - Scope: GroupBy's three bucket fields only — the sweep of
    `vector-codecs.ts` shows no other decode-side unwrap without an
    encode twin (`signed_at` has both halves).
  - Library code is NOT affected: `packages/core/src/query` validators
    and the `GroupBy` class are untouched; the defect lives entirely in
    the rig's contract codec (fable-owned, P3-3 rig row). Vector replay
    is green (1,229/0/2,022) because no corpus vector re-encodes a
    GroupBy carrying a float-spelled bucket through an output diff.
- Why the B2-BIND/arbiter fuzz missed it: both post-`2015565` runs
  (seed 83155107, 5,863 then 5,882 examples) were `--targets`-restricted
  to the 11 B2 validator families — `codec_roundtrip` last ran at the B0
  gate, BEFORE the codec change. Process note for the standing posture:
  a rig-codec change must re-run `codec_roundtrip` (at minimum) before
  its task closes, not wait for the next batch gate.
- Why seed 52794688 caught it and 21091621/28631260 did not: the
  divergence needs `codec.roundtrip` to draw a GroupBy with a
  float-valued bucket; the draw is seed-dependent, and `strategies.py`
  grew between the B0 gate and now (B2 families + arbiter domain
  extensions), so the same seed explores a different value sequence than
  it did at the B0 gate (where 52794688 ran codec_roundtrip 512/512
  clean against the PRE-`2015565` codec that round-tripped carriers
  unchanged).

---

## 2026-08-15 — B2 gate, attempt 2: **GATE CLOSED (all clean)**

- Remediation first (unblock path step 1, TS commit `ad830fb`): the
  GroupBy contract codec gained decode-time float-ness memory — the
  three bucket fields that ARRIVE as `$type: float` carriers are
  recorded in a module-level `WeakMap` at `construct` and re-tagged
  `{$type: "float", value: pythonFloatStr(v)}` at encode (same
  integral-finite guard as Python `_encode_common`'s rich-payload
  tagging); int buckets stay raw (Python annotation `int | float |
  None`, `types.py:8367-8373`). Red-first locks in
  `conformance-runner/test/codecs.test.ts` (4 tests, both directions).
  Single-family `codec_roundtrip` re-runs, all clean at 512 examples /
  0 skips / 0 divergences each: seeds **52794688** (the diverging one),
  **21091621**, **28631260**. Repro
  `repros/2026-08-16-codec-roundtrip.json` DELETED after the clean
  re-run (resolved; unblock path step 2).
- Commands (re-runnable; the standard full-suite form):

  ```bash
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 3343231 --report json    # fresh
  # B0-gate seed replays:
  #   --seed 28631260 / --seed 52794688
  ```

- Bridges: oracle-py @ ts-port/phase2-contract-support (post-3bb49eb
  tree), oracle-ts @ main `ad830fb` (the remediation HEAD; identical
  library surface at the gate commit — the gate touches only
  batch-status/ignore files), corpus pin b5c1369.
- Targets: all **33** registered (`ALL_TARGETS`, cumulative through B2).
- Totals, ALL THREE runs identical: **17,163 examples, 2,539 skips,
  0 divergences** → exit 0, status `ok`:
  - fresh seed **3343231**;
  - B0-gate seed **28631260** replay;
  - B0-gate seed **52794688** replay (attempt 1's diverging seed — now
    runs the full 17,163 incl. `codec_roundtrip` 512/512).
- Skips (all explained, protocol §4.2, identical across runs — 2,539 =
  the five B3-pending Phase-1 families): `build_filter_entry` 508,
  `build_segfilter_entry` 508, `filter_to_selector` 508,
  `filters_to_selector` 510, `normalize_on_expression` 505. Every
  both-bridge family ran >= 504 examples (>= the P2-9 500 budget).
- Raw harness JSON: `2026-08-15-b2-gate-attempt2-seed3343231.json` +
  `2026-08-15-b2-gate-attempt2-seed28631260-verify.json` +
  `2026-08-15-b2-gate-attempt2-seed52794688-verify.json`.
- GF4 oracle probes re-run at the remediation HEAD: 11/11 B2 apis
  answer call DATA on BOTH bridges, canonical outcomes pairwise equal
  (probe = the first `PHASE3_B2_TARGETS` edge call per api; bridge
  identities py 0.2.1 / ts 0.0.0, both @ source_commit b5c1369,
  protocol 1.1).
- **STANDING POSTURE RULE (adopted from the attempt-1 process note,
  P3-7)**: any change to rig codec code (`vector-codecs.ts`,
  `codecs.ts`, canonicalizers) re-runs `codec_roundtrip` (at minimum)
  before its task closes — never wait for the next batch gate. Both
  post-`2015565` fuzz runs were `--targets`-restricted to the 11 B2
  families, which is how the attempt-1 regression sat invisible.
