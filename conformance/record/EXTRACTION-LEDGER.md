# PR-5 Extraction Ledger — count reconciliation against the D10 ledger

Design of record: `context/phase1/design/phase1-design.md` D10 ("Count
reconciliation ledger") and D3 (manifest). Every D10 line is reproduced
below with the measured actual next to the estimate. All actuals come from
the committed `conformance/vectors/manifest.json` produced by the final
extraction run.

## Invocation

```bash
uv run python -m pytest tests -p conformance.record.plugin \
  --mp-record-vectors=conformance/vectors \
  --mp-record-date=2026-08-14 \
  --mp-record-commit=52696743b913a0c4c152deb48af987ae412b5aee \
  -o addopts="" -m "not live" -q
```

(`just conformance-record --mp-record-date=... --mp-record-commit=...` is the
equivalent recipe; it was fixed during PR-5 to use `uv run python -m pytest`
— bare `uv run pytest` cannot import the plugin because only the `-m` form
puts the repo root on `sys.path`.)

No `conformance/record/exclusions.args` file is needed: every D10 exclusion
besides `-m "not live"` is detected at runtime by the plugin (hypothesis via
`hasattr(item.obj, "hypothesis")`, CLI via `CliRunner.invoke` observation,
destructive via marker, the rest per-capture at emit time), so the corpus
denominator stays honest without brittle `-k` selectors.

## Headline counts (manifest `counts`)

| Metric | Value |
|---|---|
| Total vectors | **2,536** |
| `builder` | 1,302 |
| `validation-error` | 64 |
| `wire` | 1,170 |
| `with_setup` (wire vectors with `call.setup[]`) | 116 |
| Bundles | 137 |
| Record run | 6,768 passed, 1 skipped, 556 deselected, 0 failed under the D1.4 freeze |

By capability: auth 39, bookmarks 264, cohorts 99, data-governance 58,
discovery 95, engage 199, entities 587, filters 107, flows 51, funnels 117,
pagination 39, replays 35, retention 76, segmentation 67, streaming 23,
validation 680. (`manifest.json` is authoritative; this table is a prose
snapshot of the final run.)

## D10 exclusion table — estimate vs actual

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
| `unserializable_input` | expected ~0 | **19** | Callsites in `manifest.exclusion_details`. Two sub-families: (a) `unittest.mock` objects passed as entry-point arguments (rejected by the codec — audit finding F2; e.g. the rotating-`TokenResolver` freshness tests and `MagicMock(spec=CohortDefinition)`); (b) per-request-varying resolver bearers (D5.2 refinement). Each is a mock-behavior contract a vector cannot carry; Layer-3 translated tests own them. |
| `uncoded_raise` | ceiling ~38 VE + 7 TE + 124 pydantic sites | **14** | R5.5 exclusions with the worklist in `exclusion_details.uncoded_raise`. Far below ceiling because most uncoded-raise TESTS never touch a registry entry point (they unit-test types directly → `no_seam_hit`). |
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

## Builder/wire classification vs D10 net estimates

| D10 line | Estimate | Actual | Note |
|---|---|---|---|
| Builder-classified net | ~1,500 | 1,302 builder + 64 validation-error = **1,366** | The estimate double-counted tests that fire a builder through a facade AND assert only via the wire (those emit once), and ~130 uncoded-raise/enum/no-seam builder-file tests fell out of the denominator as designed. |
| Wire-classified net | ~1,330–1,360 | **1,170** | The gap is exactly the (unbudgeted-downward) `wire_call_no_transport` 610 bucket: recon counted per-FILE wire membership; per-test seam-firing classification (D1.3) is stricter. |
| Inflators (dual-seam, `-N` ordinals) | unbudgeted | present (116 `with_setup`, `-N` ids in bundles) | Positive but small, as predicted. |
| Extraction-supported floor | ~2,850 | **2,536** | See target statement below. |

## The ≥3,000 target (D10 / plan Phase-1 item 1)

**Actual extracted total: 2,536 — a shortfall of 464 against the 3,000
target, reported here per the D10 protocol (never papered over with
filler).** The ledger above reconciles every line: the shortfall is
concentrated in (a) the wire net (−160 to −190 vs estimate, all accounted
in `wire_call_no_transport`), and (b) the builder net (−134, accounted by
single-emission of dual-path tests and the uncoded-raise/no-seam
denominator). PR-7's authored budget (~60–80 vectors: compat, wire-stub,
9 uncovered codes, phase008 parse, rrweb seed, chunk vectors,
test_local_clock replacements, enums snapshot) does not close the gap.
The corpus is the honest maximum the suite supports under the D10 rules.

## Determinism proof (D3/D8)

The full extraction was run twice back-to-back with identical injected
stamps and `diff -r` (excluding the pre-existing `.gitkeep`) over the two
output trees: **byte-identical** (`DIFF_EXIT=0`). Earlier double-runs
caught and fixed a real nondeterminism (jittered virtual-sleep ticks
accumulating across tests — see EXTRACTION-AUDIT.md finding list).

## Extractor changes made during PR-5 (all fixed before the final run)

See `conformance/record/EXTRACTION-AUDIT.md` for the full finding list
(F1–F4 plus the pre-audit fixes B1–B5); every fix landed as code +
regression test in the PR-5 fix commit, and the corpus was re-extracted —
vectors were never hand-edited.
