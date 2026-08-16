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

---

## 2026-08-15 — B3 gate: **GATE CLOSED (all clean, after one rig-strategy remediation)**

- **Attempt 1 (BLOCKED — harness transport crash, not a divergence)**: the
  full-suite replays at seeds **3343231** and **28631260** crashed with
  `UnencodableValueError: value nesting exceeds the codec depth guard`
  inside `encode_input_kwargs`, falsifying example
  `bookmark_schema.validate_with_pydantic` with a deeply-nested `value`.
  Root cause (rig strategy bug, fable-owned): `_B3_LEAF_VALUES` carries
  module-level MUTABLE containers (`{}`, `{"k": 1}`, `[{}]`);
  `_b3_schema_calls` inserted them BY REFERENCE (`st.sampled_from`
  returns the constant itself) and later arms wrote through them
  (`_b3_set_path` intermediate-dict creation, direct key writes when
  `value` IS a drawn leaf), so nesting accumulated ACROSS examples until
  the depth guard fired — seed-dependent, which is why the B3-BIND run
  (64091337) and the arbiter re-run (84150301) stayed clean. Seeds
  40075993 (fresh) and 52794688 passed attempt 1 (23,022 ex / 0 div).
- **Remediation (red-first)**: new
  `TestB3SchemaCallDomainIntegrity` lock in
  `conformance/tests/test_fuzz_harness.py` — 300 derandomized draws must
  (a) never alias a mutable `_B3_LEAF_VALUES` entry (identity walk),
  (b) always ship through `encode_input_kwargs`, (c) leave the constants
  deep-equal to a pre-run snapshot; red pre-fix on (a). Fix: `_b3_leaf()`
  helper deep-copies at draw time (the same discipline the choice-3
  graft arm already applied via a json round-trip); all 5
  `sampled_from(_B3_LEAF_VALUES)` mutation-arm sites now route through
  it. Domain sequence is unchanged (same draws, fresh objects); prior
  clean RUN records explored a partially-dirtied value stream and stay
  valid as recorded history.
- **Attempt 2 (CLEAN)**: standard full-suite form (all **45** registered
  `ALL_TARGETS` families, cumulative through B3) + the K4 doubled-budget
  selector top-up per seed:

  ```bash
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 40075993 --report json    # fresh
  # prior-gate seed replays: --seed 3343231 / 28631260 / 52794688
  # K4 doubled budget, per seed:
  #   --targets filter_to_selector,filters_to_selector --examples 1000
  ```

- Totals, ALL FOUR seeds identical: full suite **23,022 examples /
  0 skips / 0 divergences**; selector top-up **2,044 examples (1,020 +
  1,024) / 0 / 0**. Exit 0, status `ok`, no repros written. Raw JSONs:
  `2026-08-15-b3-gate-seed{40075993,3343231,28631260,52794688}{,-selectors1000}.json`.
- **Skip ledger EMPTY**: `skipped_per_target` is 0 for all 45 families —
  the five Phase-1 pending-skip families went live at B3-BIND, and the
  B2-era 2,539-skip ledger is fully discharged (first all-live full-suite
  run of the program). Under-500 families are the two documented
  finite-domain exhaustions only (`build_date_range_family` 101,
  `build_time_section_family` 485 — every possible probe ran).
- Bridges: oracle-py @ ts-port/phase2-contract-support, oracle-ts @ main
  (B3 gate working tree), both `source_commit 70c904dc598d…`, protocol
  1.1, corpus pin 70c904d.
- Oracle probes (P3-2e step 3): **17/17 B3 apis** answer call DATA on
  BOTH bridges, canonical outcomes pairwise equal (probe = one edge call
  per api from the api's own strategy family; same script as B3-BIND).
- Referees at this gate (P3-7): (a) ajv — NEW runner feed
  (`differential/test/bookmark-referee-feed.test.ts`): 98 insights-shaped
  B3 builder outputs fed, 94 ACCEPT + **4 expected-and-disclosed
  dataGroupId REJECTs** (int-vs-string contract mismatch, filed
  `context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md`,
  pinned exactly in the test); (b) bookmark_parser round-trip: structural
  **314/314 ACCEPT**, deep **123 ACCEPT / 2 REJECT / 189 SKIP** — the 2
  are the standing frequency-filter true positives (expected-and-
  disclosed, exit 1 by design), byte-identical reports modulo
  `runtime_seconds`.

---

## 2026-08-16 — B4 gate: **GATE CLOSED (all clean, first attempt)**

- Standard full-suite form (P3-7): all **45** registered `ALL_TARGETS`
  families — the cumulative surface is UNCHANGED from B3 by design:
  B4's 184 wire api names have no oracle `call` surface (D14 / packet
  b4-packets.md §Binding plan — "nothing to register beyond the
  bindings"), so the gate registers no new fuzz targets and the
  newly-registered-api probe of P3-2e step 3 is vacuously satisfied
  (stated for the record; the B3 17/17 probe record stands as the
  latest registration probe).

  ```bash
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 53062695 --report json    # fresh
  # prior-gate seed replays: --seed 3343231 / 28631260 / 52794688 / 40075993
  ```

- Totals, ALL FIVE seeds identical: **23,022 examples / 0 skips /
  0 divergences** per seed; exit 0, status `ok`, no repros written.
  Seeds: fresh **53062695** + replays of EVERY prior gate seed —
  **3343231** (B2 fresh), **28631260** (B0), **52794688** (B0),
  **40075993** (B3 fresh). Raw JSONs:
  `2026-08-16-b4-gate-seed{53062695,3343231,28631260,52794688,40075993}.json`.
- Under-500 families: only the two documented finite-domain exhaustions
  (`build_date_range_family` 101, `build_time_section_family` 485).
  `skipped_per_target` all-zero (the ledger stays empty since B3).
- Bridges: oracle-py 0.2.1 @ ts-port/phase2-contract-support, oracle-ts
  0.0.0 @ main (B4 gate working tree — post-flip, library surface
  identical to the arbitrated HEAD `a24a58d`), both
  `source_commit 70c904dc598d…`, protocol 1.1, corpus pin 70c904d.
- `repros/` unchanged: exactly the two RESOLVED P2-9 triage records —
  non-blocking.
- Wire coverage note: the B4 R10.9 evidence lives in the six shard
  RUN records (VectorFetch status-branch matrices, C1 39/39 · C2 52/52
  · C3 65/65 · C4 59/59 · C5 75/75 · C6 56/56, re-run at arbitration)
  — wire methods are locked by the 843 corpus vectors + translated
  Layer-3, not by this bridge suite (D14 scope).

---

## 2026-08-16 — B5 gate: **GATE CLOSED (all clean, after one rig-strategy remediation)**

- Standard full-suite form (P3-7): all **54** registered `ALL_TARGETS`
  families — the cumulative surface grew by the 9 B5-BIND registrations
  (`PHASE3_B5_TARGETS`: the five `workspace.build_*params` facade
  families + `replay_{url_normalizer,default_label,selector_label}` +
  `rrweb_analyze_family`). The B5 wire members (all other
  `workspace.*`/`replays.*` names) have no oracle call surface and are
  exempt (D14).

  ```bash
  uv run python -m conformance.differential.fuzz_harness \
    --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
    --examples 500 --seed 47824574 --report json    # fresh
  # prior-gate seed replays: --seed 3343231 / 28631260 / 52794688 / 40075993 / 53062695
  ```

- **Rig-strategy remediation (B3-gate precedent, one iteration)**: the
  first replay pass was clean on 4 of 6 seeds; seeds **3343231** and
  **52794688** each drew ONE `rrweb_analyze_family` divergence — the
  console-payload member `[18.0, None]` joined into the console message
  (py `"18.0 None"` / ts `"18 None"`), i.e. the **Discrepancy #12
  sanctioned class** (the "rrweb console-message join" surface named in
  the discrepancy itself) surfacing through a strategy-domain gap: the
  B5-BIND F1 exclusions covered filter-value/bucket/metadata slots but
  left the integral float in the console-payload slot. Remediated in
  `strategies.py` (`[18.0, None]` → `[18.5, None]` + #12 domain note —
  fractional floats spell identically in both runtimes; the shrunken
  repro `2026-08-16-rrweb_analyzer-analyze.json` was verified
  #12-class and deleted with the fix). ALL SIX seeds then re-run
  full-suite against the final domain.
- Totals, ALL SIX seeds identical: **27,577 examples / 0 skips /
  0 divergences** per seed; exit 0, status `ok`, no repros written.
  Seeds: fresh **47824574** + replays of EVERY prior gate seed —
  **3343231** (B2 fresh), **28631260** (B0), **52794688** (B0),
  **40075993** (B3 fresh), **53062695** (B4 fresh). Raw JSONs:
  `2026-08-16-b5-gate-seed{47824574,3343231,28631260,52794688,40075993,53062695}.json`.
- Under-500 families: only the two documented finite-domain exhaustions
  (`build_date_range_family` 101, `build_time_section_family` 485).
  `skipped_per_target` all-zero (ledger empty since B3).
- Bridges: oracle-py 0.2.1 @ ts-port/phase2-contract-support, oracle-ts
  0.0.0 @ main (B5 gate working tree — post-flip `c66b2d9`+), both
  `source_commit 70c904dc598d…`, protocol 1.1, corpus pin 70c904d.
- Oracle probes (P3-2e step 3): **9/9 newly registered builder-kind
  apis** answer call DATA on BOTH bridges, canonical outcomes pairwise
  equal (probe = the family's first R10.9 edge call; the five
  `workspace.build_*params`, three `replay_labels.*`,
  `rrweb_analyzer.analyze`; wire names exempt).
- `repros/` back to exactly the two RESOLVED P2-9 triage records —
  non-blocking.
- Referees at this gate (P3-7 conditional clause, b5-packets.md §7.4 —
  `workspace.build_params` EMITS insights bookmark params): (a) ajv —
  feed extended with the 115 `build_params` full payloads AS-IS (213
  fed total): 208 ACCEPT + **5 pinned expected-and-disclosed
  dataGroupId REJECTs** (the 4 standing B3 clause-level pins + ONE NEW
  SITE: sections-level `dataGroupId` int, `workspace.py:2278`, rejected
  as `/sections: must NOT have additional properties` — addendum filed
  in `context/phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md`);
  (b) bookmark_parser round-trip over the regenerated (byte-identical)
  handoff: structural **314/314 ACCEPT**, deep **123 ACCEPT / 2 REJECT
  / 189 SKIP** — the 2 are the standing frequency-filter true positives
  (expected-and-disclosed, exit 1 by design), reports byte-identical to
  B3 modulo `runtime_seconds`. No NEW reject on either referee.

## 2026-08-16 — B6 gate: **GATE CLOSED (all clean, after one library-twin fold)**

- **Scope**: playbook P3-2e item 3 + P3-7 at the B6 gate. The B6 batch
  itself registered ZERO new oracle families (all 154 BIND names are
  wire-kind — `b6-packets.md` §11.5; wire names have no oracle call
  surface and are probe-exempt). The GATE task added ONE builder-kind
  family while executing the B5-notes outbound ledger item 5
  (`pythonFloatCoerce`, the R11.7 non-string `float(x)` ladder):
  `compat.python_float_coerce` — TS `compat/python-float-coerce.ts` +
  binding beside `compat.python_float`, Python reference
  `pycompat_ref.python_float_coerce` + registry `_gate_entries()`,
  strategy `_PYTHON_FLOAT_COERCE` in `PHASE3_TARGETS` (safe-int /
  finite-float / bool / None / list / dict / grammar-adjacent-string
  domain; 14 R10.9 edges; unsafe ints and non-finite input floats are
  documented omissions — R4.5 transport bar and the identity arm; the
  `float(10**400)` OverflowError branch is locked TS-side by
  `python-float-coerce.test.ts`).
- **Oracle probe** (P3-2e step 3): the new family answered call DATA on
  BOTH bridges — dedicated family run at seed 628997442:
  **514 examples (500 + 14 edges) / 0 skips / 0 divergences**.
- **Cumulative surface**: 55 families (54 prior + the above).

```bash
uv run python -m conformance.differential.fuzz_harness \
  --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
  --examples 500 --seed 628997442 --report json    # fresh
# prior-gate seed replays: --seed 3343231 / 28631260 / 52794688 / 40075993 / 53062695 / 47824574
```

- **One REAL rig-observable bug caught and fixed (library-twin fold)**:
  the first 55-family pass drew ONE divergence on seed **3343231**
  (`cohort_family`, shrunken repro `types.CohortCriteria.has_property`
  `{operator: "junk"}`): py `KeyError` vs ts `KeyError2`. Root cause:
  TWO same-named `KeyError` classes (the module-local P2-9 mirror in
  `types/query-params/cohort.ts` + the canonical
  `query/python-builtins.ts` twin); the gate's compat import re-ordered
  the esbuild oracle bundle, renaming the cohort copy to `KeyError2`
  (the bridge compares `constructor.name`, oracle-protocol.md §4.1).
  Previously invisible: the python-builtins twin is thrown only by B5
  discovery parsers (wire — no oracle surface). FIXED per
  python-builtins' own R10.4 watch note — the duplicate DELETED,
  `cohort.ts` imports the canonical twin (import-free leaf, no cycle);
  fix verified by a direct oracle probe of the repro input
  (`class: "KeyError"`); repro file deleted with the fix (B3/B5-gate
  precedent). A 54-family pre-addition pass had been clean on all
  seven seeds (27,577/0/0) — the bundle order flip is what exposed the
  latent collision.
- Totals, ALL SEVEN seeds identical over the final tree:
  **28,091 examples / 0 skips / 0 divergences** per seed
  (`python_float_coerce` 514 each); exit 0, status `ok`, no repros
  written. Seeds: fresh **628997442** + replays of EVERY prior gate
  seed — **3343231** (B2 fresh), **28631260** (B0), **52794688** (B0),
  **40075993** (B3 fresh), **53062695** (B4 fresh), **47824574** (B5
  fresh). Raw JSONs:
  `2026-08-16-b6-gate-seed{628997442,3343231,28631260,52794688,40075993,53062695,47824574}.json`.
- Under-500 families: only the two documented finite-domain exhaustions
  (`build_date_range_family` 101, `build_time_section_family` 485).
  `skipped_per_target` all-zero (ledger empty since B3).
- Bridges: oracle-py 0.2.1 @ ts-port/phase2-contract-support, oracle-ts
  0.0.0 @ main (B6 gate working tree), both `source_commit
  70c904dc598d…`, protocol 1.1, corpus pin 70c904d.
- `repros/` back to exactly the two RESOLVED P2-9 triage records —
  non-blocking.
- Referees at this gate (P3-7 — REQUIRED, bookmark-touching batch):
  (a) ajv runner feed — no new feed slot (W3 validates/passes through
  ALREADY-BUILT params; construction stayed B3/B5): 213 fed, **208
  ACCEPT + the 5 pinned expected-and-disclosed dataGroupId REJECTs**
  (pin-exactness asserted by the test); (b) bookmark_parser round-trip
  over the regenerated (byte-identical, 314-entry) handoff: selftest
  controls passed for both oracles first; structural **314/314
  ACCEPT**; deep **123 ACCEPT / 2 REJECT / 189 SKIP_NON_INSIGHTS** —
  the 2 standing frequency-filter true positives only (exit 1 by
  design). **No NEW reject on either referee — non-blocking.**

## 2026-08-16 — B7 gate: **GATE CLOSED (all clean, first attempt)**

- **Scope**: playbook P3-2e item 3 + P3-7 at the B7 gate. B7 registered
  **ZERO new oracle families**: the batch's only corpus api
  (`region_probe.probe_region`) is wire-kind (probe-exempt — no
  `oracle.call` surface), and the auth surface as a whole has no
  cross-language fuzz bridge (playbook Risk 7 — compensating controls
  are full Layer-3 translation, the DOUBLED review pairs, and the two
  R10.9 local-mini-model harnesses recorded in
  `context/phase3/notes/B7-A{1,2}-notes.md`). `strategies.py` untouched
  by any B7 commit; cumulative surface stays **55 families**.
- **Differential full-suite regression** over the existing registered
  surface, fresh seed + replay of EVERY prior gate seed:

```bash
uv run python -m conformance.differential.fuzz_harness \
  --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
  --examples 500 --seed 715310894 --report json    # fresh
# prior-gate seed replays: --seed 3343231 / 28631260 / 52794688 / 40075993 / 53062695 / 47824574 / 628997442
```

- Totals, ALL EIGHT seeds identical: **28,091 examples / 0 skips /
  0 divergences** per seed; exit 0, status `ok`, no repros written.
  Seeds: fresh **715310894** + replays of EVERY prior gate seed —
  **3343231** (B2 fresh), **28631260** (B0), **52794688** (B0),
  **40075993** (B3 fresh), **53062695** (B4 fresh), **47824574** (B5
  fresh), **628997442** (B6 fresh). Raw JSONs:
  `2026-08-16-b7-gate-seed{715310894,3343231,28631260,52794688,40075993,53062695,47824574,628997442}.json`.
- Under-500 families: only the two documented finite-domain exhaustions
  (`build_date_range_family` 101, `build_time_section_family` 485).
  `skipped_per_target` all-zero (ledger empty since B3).
- Bridges: oracle-py 0.2.1 @ ts-port/phase2-contract-support, oracle-ts
  0.0.0 @ main (B7 gate tree, post-flip commit), both `source_commit
  70c904dc598d…`, protocol 1.1, corpus pin 70c904d.
- `repros/` unchanged: exactly the two RESOLVED P2-9 triage records —
  non-blocking.
- Referees at this gate (P3-7): **not required and not run** — B7
  touches no bookmark source and emits no bookmark payloads
  (name-only diff over all five B7 TS commits: zero `bookmarks/`
  contact; check recorded in `context/phase3/notes/B7-notes.md`).
- Conformance checkpoint at the same gate commit: **3,244 PASS /
  0 FAIL / 7 UNPORTED** @ corpus 70c904dc (delta +14 = the 14
  `region_probe.probe_region` vectors; the 7 remaining are
  `oauth_flow.refresh_tokens`, B8).
