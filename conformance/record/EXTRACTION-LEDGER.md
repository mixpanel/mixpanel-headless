# Extraction Ledger — count reconciliation (D10)

Design of record: `context/phase1/design/phase1-design.md` D10 ("Count
reconciliation ledger") and D3 (manifest), plus the addendum coding-pass
design (`context/phase1/addendum/coding-pass-design.md`) and GATE-VERDICT
recommendations R1/R2/R3 (`context/phase1/audit/GATE-VERDICT.md` §8).
`conformance/vectors/manifest.json` is authoritative; every table below is
a prose snapshot of the committed extraction run.

## P2-1 re-extraction (2026-08-15) — Phase-2 recorder-coverage closure

### Invocation

```bash
uv run python -m pytest tests -p conformance.record.plugin \
  --mp-record-vectors=conformance/vectors \
  --mp-record-date=2026-08-15 \
  --mp-record-commit=0cc33b0ecc750acbe4929408d00542db9d555d2a \
  -o addopts="" -m "not live" conformance/tests/test_coverage_cases.py -q
```

The trailing path comes from `conformance/record/exclusions.args` (now an
INCLUSION selector — see README): `tests/` is frozen during Phase 2, so the
P2-1 coverage-closure cases live in `conformance/tests/test_coverage_cases.py`
and join the record run through the existing `$(cat exclusions.args)` seam in
both the justfile recipe and the CI drift step (no invocation change needed).
The stamped commit is the `ts-port/phase2-contract-support` code-half commit
(registry additions + coverage cases + contract generator), per the AD-6
precedent. Record run: **7,143 passed, 1 skipped, 556 deselected, 0 failed**
under the D1.4 freeze (+27 collected: the new coverage-case tests).

### Headline counts (manifest `counts`)

| Metric | AD-6 baseline | P2-1 actual | Delta |
|---|---|---|---|
| **Extracted vectors (manifest total)** | 3,007 | **3,031** | +24 |
| `builder` | 1,744 | 1,768 | +24 |
| `validation-error` | 65 | 65 | 0 |
| `wire` | 1,198 | 1,198 | 0 |
| Bundles | 154 | 157 | +3 |

New bundles: `funnels/test_coverage_cases.jsonl`,
`retention/test_coverage_cases.jsonl`, `cohorts/test_coverage_cases.jsonl`.

### Vector-id churn vs the AD-6 corpus (honest diff)

**25 added, 1 removed, 3,006 shared.** Added, by `call.api`:
`types.CohortCriteria.did_not_do_event` 10, `types.FunnelStep` 6 (4 from the
coverage cases + 2 from pre-existing `tests/test_validation_funnel.py`
constructions whose EV1 raises were previously invisible — the seam did not
exist), `types.RetentionEvent` 4, `types.CohortCriteria.property_is_set` 3
(2 coverage cases + 1 RESEATED vector — see below),
`types.CohortCriteria.property_is_not_set` 2. The 1 removed id is
`cohorts/types.cohortcriteria.has_property/test_cohort_definition-...-test_cd7_property_is_set_empty_name`:
that test calls `property_is_set("")`, which previously recorded under the
inner `has_property` seam; with `property_is_set` registered, the OUTER seam
now owns the vector (re-entrancy guard) under its own `call.api` — the
logical contract persists under the corrected name.

`conformance/vectors/api-index.json` now carries **44 `types.*` entries**
(39 + the 5 P2-1 closures), the Phase-2 design C10/P2-1 done-criterion.

### Determinism / drift proof

Full re-extraction into `/tmp/re-extract` with identical injected stamps,
then `uv run python -m conformance.record.diff /tmp/re-extract
conformance/vectors`: byte-clean in both directions (exit 0). Corpus runner
at this commit: **3,179/3,179 passed** (3,031 extracted + 148 authored).

### Contract artifacts (P2-1, same commit family)

`conformance/contract/{error-codes,literal-aliases,tag-universe,model-coverage}.json`
were generated AFTER this extraction with
`--generated-from 0cc33b0ecc750acbe4929408d00542db9d555d2a`; re-runs are
byte-identical (verified via `cmp` against a second run). The tag universe
(85 observed tags + zero-filled `date` built-in, 80 rich) is produced by a
JSON-aware `$type`-key walk and cross-verified in
`conformance/tests/test_generate_contract.py` against an independently
implemented `object_pairs_hook` scan — never grep.

## AD-6 re-extraction (2026-08-15) — post-coding-pass baseline

### Invocation

```bash
uv run python -m pytest tests -p conformance.record.plugin \
  --mp-record-vectors=conformance/vectors \
  --mp-record-date=2026-08-15 \
  --mp-record-commit=d5627564d7e5a6711c4980f72187563f27e4c7f7 \
  -o addopts="" -m "not live" -q
```

The stamped commit is the `ts-port/phase1-addendum` HEAD at extraction
time (after the AD-6 R2 emit fix and R9 smoke fix, before the generated
vectors commit). Record run: **7,116 passed, 1 skipped, 556 deselected,
0 failed** under the D1.4 freeze.

### Headline counts (manifest `counts`)

| Metric | PR-5 baseline | AD-6 actual | Delta |
|---|---|---|---|
| **Extracted vectors (manifest total)** | 2,530 | **3,007** | +477 |
| `builder` | 1,302 | 1,744 | +442 |
| `validation-error` | 64 | 65 | +1 |
| `wire` | 1,170 → 1,164* | 1,198 | +34 |
| `with_setup` | 116 | 118 | +2 |
| Bundles | 137 | 154 | +17 |

*The PR-5 ledger prose said 1,170; the committed manifest said 1,164 (the
stale-headline finding L1-F3). This table re-baselines from manifests only.

By capability: auth 39, bookmarks 412 (+148), cohorts 186 (+87),
data-governance 62 (+4), discovery 95, engage 233 (+34), entities 608 (+26),
filters 190 (+83), flows 62 (+11), funnels 141 (+24), pagination 39,
replays 94 (+60), retention 76, segmentation 67, streaming 23, validation 680.

### Authored vectors (unchanged by extraction; runner-countable)

| Family | Vectors |
|---|---|
| Seed authored (compat, wire-stub, uncovered codes, phase008 parse, rrweb, chunks, date-builders, live-query transforms) | 79 |
| AD-5 storybook parse harvest (E1) | 69 |
| **Authored total** | **148** |

(JSONL line counts additionally include 13 authored `$bundle` records; the
9 wirestub wire vectors run only under the TS runner's `VectorFetch` and
ARE part of the 79.)

### Corpus total vs the ≥3,000 target (R1 re-baseline)

**3,007 extracted + 148 authored = 3,155 — the 3,000 target is MET
(+155).** The PR-5 shortfall (2,536-era headline; true baseline
2,530 + 79 = 2,609, gap 391) is closed by exactly the two sanctioned
addendum tracks: the E2 coding pass recovered all 14 `uncoded_raise`
exclusions and added +477 extracted vectors (within the design's
plausible band once the §5 guard-entry registry extension is counted),
and the E1 storybook harvest added 69 authored parse vectors.
Per-site yield check (GATE-VERDICT R1 expectation ≥2 recordable
tests/site): 138 coded sites produced 442 net new builder-kind vectors —
≈3.2 per site.

### Exclusion table — AD-6 actual vs PR-5 actual

| Category | PR-5 | AD-6 | Note |
|---|---|---|---|
| `live` (deselected) | 556 | 556 | unchanged |
| `hypothesis` | 537 | 537 | runtime-detected, unchanged |
| `cli` | 506 | 506 | unchanged |
| `no_seam_hit` | 2,668 | **2,142** | −526: guard-entry registration (coding-pass §5 item 2) turned pure constructor-guard tests into seam-hitting recordings |
| `wire_call_no_transport` | 610 | **638** | +28: new B3 tests for workspace/api_client guards that raise BEFORE transport (`WS*`/`WR*`/`AC*` codes) — exactly the design §4-B3 caveat; those guard contracts ride Layer 3 |
| `uncoded_raise` | 14 | **0** | the E2 worklist fully recovered; residual is zero (key absent from the manifest) |
| `unserializable_input` | 25 | 25 | unchanged |
| `raw_transport_no_entrypoint` | 34 | 34 | unchanged |
| `layer3_deferred` | 1 | 1 | MAX_PAGES static patch only |
| `test_local_clock` | 1 | 1 | unchanged |
| `fs_dependent` | 4 | 4 | unchanged |
| `skipped_upstream` | 1 | 1 | contract placeholder |

### Vector-id churn vs the PR-5 corpus (honest diff)

509 ids added, 32 removed, 2,498 shared. Of the 32 removed:

- 8 are D3 ordinal reshuffles (`-N` suffix moves when a test emits more
  vectors than before); the logical vector persists under a new ordinal.
- 24 are nested-call suppressions: tests whose inline
  `CohortDefinition.to_dict` / `types._sanitize_raw_cohort` /
  `bookmark_builders.build_filter_entry` recordings previously fired at
  depth 0 now run INSIDE newly registered outer seams
  (`Filter.in_cohort`, `CohortDefinition.all_of`,
  `build_flow_property_filter`, `build_flow_cohort_filter`, …) and are
  suppressed by the plugin's re-entrancy guard. Each such test still
  emits its outer-seam vector (e.g. 9/16/32 new vectors for the three
  B2-registered bookmark_builders functions), and direct-call coverage
  of the inner seams persists from their dedicated tests.

Among the 2,498 shared ids, exactly **2** changed `call.session`: the two
pin-lifecycle vectors (see R2 below). No other shared vector changed
session content.

### Determinism proof (D3/D8)

The full extraction was run twice back-to-back with identical injected
stamps into two fresh directories; `diff -r` over the two trees:
**byte-identical** (`DIFF_EXIT=0`). Diff-tool sensitivity proven by a
perturbed-byte control (one digit flipped in a manifest copy →
`DIFF_EXIT=1`).

### Corpus runner

`python -m conformance.runner --vectors conformance/vectors --report json`
at the vectors commit: **3,155/3,155 passed, 0 failed** (runner-reported
`runtime_seconds` 2.2; wall time 2.6 s via `/usr/bin/time -p` including
corpus load). Replaying the new coded-guard vectors required two runner
extensions (committed with AD-6, before the vectors commit):
`error_only` target resolution (constructor targets call the class;
classmethod targets bind through the class) and VAR_POSITIONAL input
binding (`Filter.list_contains(*item_filters)` replays positionally).
The TS runner needs the mirrored mapping only when Phase 3 ports these
families (unported vectors are counted, not failed) — noted for AD-9.

## GATE-VERDICT R2/R3 dispositions (recorded per the addendum task)

- **R2 (pin-lifecycle precondition) — IMPLEMENTED.** `emit.py` now
  encodes `call.session` from the FIRST wire call of a vector (the
  pre-setup state) instead of the measured call's post-mutation session.
  The two `TestPinLifecycle` vectors regain `workspace_id: 777` in
  `call.session` with their pin-clearing `api_client.use` setup entries,
  making the pin-clear contract discriminating at Layer 1 (audit L3-F1).
  Corpus-wide impact audited: exactly those 2 vectors changed.
- **R3 (credential-redaction message assertions) — LAYER-3-ONLY, by
  explicit deferral.** No `message_not_contains` field is added to the
  operative schema or the runners. The redaction-in-error-message family
  (`tests/unit/_internal/test_replays_service.py::…::
  test_transport_error_redacts_signed_credential` and the sibling
  `redact` tests in that file; audit finding L3-F2) asserts message
  CONTENT, which D6 rule 6 / R5.4 deliberately make unrepresentable in
  vectors (`_encode_error` strips messages; the schema marks
  message/suggestion/fix "deliberately unrepresentable"). The recorder
  cannot detect message-content assertions to auto-emit such a field,
  and hand-authoring wire-error vectors for the CDN fetch path would buy
  ~1 vector at the cost of a schema + dual-runner change. DISPOSITION:
  these contracts are carried by the Layer-3 translated tests
  (`test_replays_service` ports with their `not in str(error)`
  assertions intact); Layer 1 locks the class+code contract
  (`MixpanelHeadlessError` / `CDN_FETCH_ERROR`) only. If Layer 1 must
  ever stand alone, revisit via a `message_not_contains` schema field in
  BOTH runners (TS side would land in AD-9 scope).

---

## Historical: PR-5 extraction ledger (2026-08-14 baseline, superseded)

The original PR-5 reconciliation against the D10 estimates is preserved
below unchanged except for this heading; its headline counts are
superseded by the AD-6 section above (and were already flagged stale by
GATE-VERDICT L1-F3: prose said 2,536/19 where the manifest said 2,530/25).

### Invocation (PR-5)

```bash
uv run python -m pytest tests -p conformance.record.plugin \
  --mp-record-vectors=conformance/vectors \
  --mp-record-date=2026-08-14 \
  --mp-record-commit=52696743b913a0c4c152deb48af987ae412b5aee \
  -o addopts="" -m "not live" -q
```

No `conformance/record/exclusions.args` file is needed: every D10 exclusion
besides `-m "not live"` is detected at runtime by the plugin (hypothesis via
`hasattr(item.obj, "hypothesis")`, CLI via `CliRunner.invoke` observation,
destructive via marker, the rest per-capture at emit time), so the corpus
denominator stays honest without brittle `-k` selectors.

### Headline counts (PR-5 manifest `counts`)

| Metric | Value |
|---|---|
| Total vectors | 2,536 (prose; manifest said **2,530**) |
| `builder` | 1,302 |
| `validation-error` | 64 |
| `wire` | 1,170 (prose; manifest said **1,164**) |
| `with_setup` | 116 |
| Bundles | 137 |
| Record run | 6,768 passed, 1 skipped, 556 deselected, 0 failed |

By capability: auth 39, bookmarks 264, cohorts 99, data-governance 58,
discovery 95, engage 199, entities 587, filters 107, flows 51, funnels 117,
pagination 39, replays 35, retention 76, segmentation 67, streaming 23,
validation 680.

### D10 exclusion table — estimate vs PR-5 actual

| Category | D10 estimate | Actual | Reconciliation |
|---|---|---|---|
| `live` | 556 | 556 deselected | `-m "not live"` deselects at collection, so live tests never reach per-item suppression; the count is pytest's deselected total (547 tests/live + 9 integration, matching recon). Not a manifest key by design of the mechanism. |
| `hypothesis` | 558 (556 `_pbt` + 2 structural) | **537** | Runtime detection is authoritative (D10: "NOT filename-only"). `-k "_pbt"` selects 556 tests, but 21 of them are plain example-based tests colocated in `_pbt` files without `@given` — those record normally (correct per D10). The 2 structural `@given` tests in `test_query_user_structural.py` ARE runtime-detected. 537 + 21 non-PBT-in-pbt-files + 2 already counted = the 558 file-level estimate reconciles. |
| `cli` | plugin-emitted | **506** | Per-test `CliRunner.invoke` observation, as designed. |
| `destructive` | plugin-emitted | **0** | No `destructive`-marked test exists in the non-live selection (the marker rides live suites). |
| `contract-marker` / `skipped_upstream` | 1 | **1** | The self-skipping contract placeholder (test_workspace_lazy_resolve.py:110). |
| `no_seam_hit` | est. several thousand | **2,668** | Pure unit tests of config/exceptions/formatting/resolver etc. |
| `raw_transport_no_entrypoint` | est. <20 | **34** | Above estimate but same shape: P7 raw-httpx patterns (`_iter_jsonl_lines` chunk tests, OAuthFlow.login PKCE traffic — login is deliberately not a registry entry, D2 exclusion 3). Callsites listed in `manifest.exclusion_details`. |
| `layer3_deferred` | est. 10-25 | **1** | Only the static MAX_PAGES-patch nodeid (D2 exclusion 2). DELIBERATE deviation for the duration-assert family: those tests (6 in `TestRetryAfterHardening`, the pagination Retry-After class) fire ordinary 429 request SEQUENCES whose vectors are fully replayable — D2 exclusion 1 defers only the sleep-DURATION math, and D10 itself mandates keeping the pagination Retry-After class ("excluding on that signal would strip the R6.1 paginator-retry invariant"). Excluding whole tests would have deleted exactly the sequence coverage smoke patches S12/S13 need, so their vectors are IN and only the duration contract is (implicitly) Layer-3. OAuth interactive login traffic lands in `raw_transport_no_entrypoint` instead (no registry entry to attribute to). |
| `test_local_clock` | est. ≤30, one file | **1** | Verified: exactly one test in the suite patches the module clock attribute (`test_bookmark_builders.py::TestBuildTimeSection::test_from_only_fills_today`). The ≤30 estimate was a file-level ceiling. PR-7 authors the RECORD_EPOCH replacement. |
| `fs_dependent` | est. <15 | **4** | Lookup-table `tmp_path` uploads; callsites in `exclusion_details`. |
| `unserializable_input` | expected ~0 | **19** (25 by final manifest) | Callsites in `manifest.exclusion_details`. Two sub-families: (a) `unittest.mock` objects passed as entry-point arguments (rejected by the codec — audit finding F2; e.g. the rotating-`TokenResolver` freshness tests and `MagicMock(spec=CohortDefinition)`); (b) per-request-varying resolver bearers (D5.2 refinement). Each is a mock-behavior contract a vector cannot carry; Layer-3 translated tests own them. |
| `uncoded_raise` | ceiling ~38 VE + 7 TE + 124 pydantic sites | **14** | R5.5 exclusions with the worklist in `exclusion_details.uncoded_raise`. Far below ceiling because most uncoded-raise TESTS never touch a registry entry point (they unit-test types directly → `no_seam_hit`). **Recovered to 0 by the E2 coding pass — see the AD-6 section.** |
| `skipped/deselected` | plugin-emitted | 1 skipped upstream | See `contract-marker` row. |
| `freeze_incompatible` (risk register #2) | — | **0** | The full record run is green under the freeze; no test was excluded for failing under it. |

New categories not in the D10 table (all plugin-emitted, counted for
denominator honesty):

| Category | Actual | Meaning |
|---|---|---|
| `wire_call_no_transport` | 610 | Wire entry points ran but no transport fired (input-validation raises before any request, mocked-out internals). No wire contract to record. |
| `wire_state_only_traffic` | 0 in final manifest (folded) | Traffic attributed only to `wire_state` calls — cannot be a measured call (D2). |
| `partial_iterator` | (see manifest) | Streaming call whose iterator the test did not exhaust — unreplayable half-consumed contract. |
| `post_measured_traffic` | (see manifest) | Entry-point traffic after the measured (last `wire_api`) call — the D2 model cannot represent it. |

Denominator check: 6,769 collected non-live − 1 skipped = 6,768 ran;
exclusion counts are per-capture/per-call (a test can contribute both a
builder vector and an exclusion), so categories intentionally do not sum to
the test count.

### Builder/wire classification vs D10 net estimates (PR-5)

| D10 line | Estimate | Actual | Note |
|---|---|---|---|
| Builder-classified net | ~1,500 | 1,302 builder + 64 validation-error = **1,366** | The estimate double-counted tests that fire a builder through a facade AND assert only via the wire (those emit once), and ~130 uncoded-raise/enum/no-seam builder-file tests fell out of the denominator as designed. |
| Wire-classified net | ~1,330–1,360 | **1,170** | The gap is exactly the (unbudgeted-downward) `wire_call_no_transport` 610 bucket: recon counted per-FILE wire membership; per-test seam-firing classification (D1.3) is stricter. |
| Inflators (dual-seam, `-N` ordinals) | unbudgeted | present (116 `with_setup`, `-N` ids in bundles) | Positive but small, as predicted. |
| Extraction-supported floor | ~2,850 | **2,536** | Superseded: see the AD-6 target section. |

### The ≥3,000 target — PR-5 statement (superseded)

The PR-5 run reported 2,536 extracted, a shortfall of 464, "the honest
maximum the suite supports under the D10 rules" at that commit. The E2/E1
addendum changed the suite (coded guard sites + new tests + storybook
harvest); the AD-6 section above is the operative target statement:
**3,155 total, target met.**

### Determinism proof (PR-5)

The full extraction was run twice back-to-back with identical injected
stamps and `diff -r` (excluding the pre-existing `.gitkeep`) over the two
output trees: **byte-identical** (`DIFF_EXIT=0`). Earlier double-runs
caught and fixed a real nondeterminism (jittered virtual-sleep ticks
accumulating across tests — see EXTRACTION-AUDIT.md finding list).

### Extractor changes made during PR-5 (all fixed before the final run)

See `conformance/record/EXTRACTION-AUDIT.md` for the full finding list
(F1–F4 plus the pre-audit fixes B1–B5); every fix landed as code +
regression test in the PR-5 fix commit, and the corpus was re-extracted —
vectors were never hand-edited.
