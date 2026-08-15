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
