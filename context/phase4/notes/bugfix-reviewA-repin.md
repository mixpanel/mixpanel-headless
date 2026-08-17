# Pair A, Lens 2 — RE-PIN INTEGRITY + REFEREE RETIREMENT (adversarial review)

Reviewer run date: 2026-08-17. Scope: Python `ts-port/python-bugfix-batch`
(bddc576..2ea6442, diff vs `ts-port/phase2-contract-support` @ c2a25c5) and TS
`main` (8fa150d..2b72ce1). All verification below was performed INDEPENDENTLY
(own scripts, fresh referee/runner executions) — not by trusting
`bugfix-batch-notes.md`. Pair-B blindness respected (no other review file read;
none existed when this review started).

## Verdict

**PASS — no blockers, no majors.** Drift accounting is clean with every changed
file bucketed; Δ math verified end-to-end; both referees run FULLY CLEAN fresh
with the disclosure pins DELETED (not bypassed); both conformance runners green
at 3,262/0/0 @ 700db99; no runner/batch-status/rig source was touched. Two
minor observations (§8).

## 1. Independent drift accounting (old pin 70c904dc → new pin 700db996)

Audited the RE-PIN commit `a1d43a5` vs its parent with a per-vector diff script
(`/tmp/repin_audit.py`, parses each changed bundle at both revs, buckets
stamp-only vs per-vector-id modified/added/removed). Result — 164 changed
files, ALL accounted:

- **150 bundles stamp-only** — verified line-level: the ONLY differing lines in
  all 150 are the `$bundle` `source_commit` lines (0 non-stamp lines changed).
- **7 bundles with vector content changes** (auth/test_auth_flow,
  bookmarks/test_bookmark_builders, bookmarks/test_query_params,
  filters/test_bookmark_builders, funnels/test_build_funnel_params,
  replays/test_api_client_sign_replays, retention/test_build_retention_params):
  - **20 MODIFIED** vector ids = EXACTLY the disclosed FIX-1 inventory:
    13 bug-(a) (9 `build_frequency_filter_entry` + 2 `build_filter_section`
    frequency + 2 `workspace.build_params` frequency) + 7 bug-(b)
    (4 `build_group_section` + insights build_params + funnel + retention
    dataGroupId). None missing, none extra.
  - **11 ADDED** vector ids, each traced to a batch test: bug (a) +1
    (`test_no_custom_property_nesting`), bug (c) +9
    (`testsensitivedata403bodyshapes-*`: falsy 0/false/null, truthy 42/1.5/true,
    list-exact, list-substring, string-body), bug (d) +1
    (`testtokenpayloadredaction-test_refresh_missing_fields_error_redacts_token_material`).
  - **0 REMOVED, 0 UNEXPLAINED.**
- **manifest.json** — byte-diffed: counts auth 39→40, filters 190→191, replays
  94→103, builder 1768→1769, wire 1198→1208, total 3,031→3,042,
  `raw_transport_no_entrypoint` 34→37 (the three added exclusions are exactly
  the `TestTokenPayloadRedaction` exchange-path members), `extraction_date`
  2026-08-15→2026-08-16, `source_commit` 70c904dc…→700db996…. Nothing else.
- Remaining 6 files of the commit: 4 referee artifacts (README, handoff.jsonl,
  last-run-structural/deep — the retirement, §4) + phase3-playbook re-pin
  bullet + bugfix-batch-notes append. All expected.

Vector-content spot checks: bug-(a) `test_basic_structure` `expect.output`
flipped from the `customProperty`-nested shape to the platform-native clause
(top-level filterType/filterOperator/filterValue, `$frequency` under
`behavior.behaviorType`, label in `value`) — only the `expect` key changed;
bug-(b) funnel vector flipped `"dataGroupId": 5` → `"globalDataGroupId": "5"`
— only `expect` changed. Matches the fix-of-record docs.

## 2. Δ math + count expectations

- Independent full-corpus re-measure at both revs (own script over `call.api`):
  old total **3,251**, new total **3,262** (Δ11 = 20 modified stay + 11 added +
  0 removed). Per-prefix deltas EXACTLY `api_client` 810→819, 
  `bookmark_builders` 134→135, `oauth_flow` 7→8; every other prefix unchanged.
  Matches the claimed per-bug Δ ((a)+1, (b)+0, (c)+9, (d)+1).
- Recorded-manifest math consistent: 3,031→3,042 (same Δ11; the constant 220
  runner-vs-manifest offset is the authored/synthetic vectors mp-record does
  not own — unchanged across the re-pin).

## 3. `3,251` grep — every survivor justified

- **Python repo**: survivors are exclusively dated historical records —
  `context/phase3/**` (gate reports, notes, packets, review resolutions),
  `conformance/differential/oracle/RUN.md` (dated gate checkpoints),
  `phase3-playbook.md` lines 4/45/58 (historical pin records; the NEW §
  at :75-81 records 3,262 = 3,251+Δ11 with the exact prefix deltas), `uv.lock`
  (coincidental hashes/sizes). NO operative assertion of 3,251 anywhere in
  conformance code/tests (grep of `conformance/` code: zero hits).
- **TS repo**: single survivor `conformance-runner/src/batch-status.ts:74` — a
  dated doc comment ("TERMINAL STATE (B8 gate, 2026-08-16) … 3,251 PASS … pin
  70c904dc"), historical, not an assertion (see §8 minor). `README.md` updated
  to 3,262 (lines 15, 593). Old-pin `70c904d` greps: Python — only dated
  differential-oracle gate reports + RUN.md + context docs; TS — only the same
  batch-status.ts comment.

## 4. Referee (b) — bookmark_parser, run FRESH (fully clean)

- Handoff regenerated from committed vectors → 314 entries, **byte-identical to
  the committed `handoff.jsonl`** (zero drift aborts).
- Selftests first, both oracles: structural `status: ok`, deep `status: ok`.
- Structural batch (jsonschema 4.26.0, PYTHONPATH=analytics): **314 ACCEPT /
  0 REJECT**, exit 0.
- Deep batch (voluptuous 0.16.0 recipe): **125 ACCEPT / 0 REJECT /
  189 SKIP_NON_INSIGHTS**, exit 0. The 2 standing frequency-filter deep REJECTs
  are GONE.
- Committed `last-run-structural.json` / `last-run-deep.json` match my fresh
  runs (314/0 and 125/0/189).
- Retirement is genuine: README "Batch results" section rewritten to
  "no standing expected-REJECT set … any REJECT is a NEW finding"; `harness.py`
  / `handoff.py` UNCHANGED in the batch diff (no code allowlist existed or was
  added). `/Users/jaredmcfarland/Developer/analytics` used read-only
  (PYTHONPATH only; its working tree untouched).

## 5. Referee (a) — ajv bookmark referee, run FRESH (fully clean)

- `npm run referee:bookmark` @ TS main 2b72ce1: **9 tests green, 0 REJECT**
  over 214 fed vectors (incl. the new no-custom-property-nesting fragment).
- Pin deletion verified in the 8fa150d diff of
  `differential/test/bookmark-referee-feed.test.ts`: the
  `EXPECTED_DATAGROUPID_REJECTS` map (4 B3 clause pins + 1 B5
  `sections.dataGroupId` pin) and its exact-set assertion are DELETED; the
  reject loop now pushes EVERY reject into `unexpectedRejects` and asserts
  `[]` — no bypass, no allowlist. Header disclosure replaced with "NO STANDING
  DISCLOSURES".

## 6. Both conformance runners, run FRESH

- Python: `uv run python -m conformance.runner --vectors conformance/vectors
  --report json` → exit 0, **total 3,262 / passed 3,262 / failed 0**.
- TS: `npm run conformance` → **3,262 / 3,262 passed / 0 failed / 0 unported
  (corpus @ 700db996cc95)**.
- Python `conformance/tests` suite: **518 passed** (the referee-routing
  drift-abort that redded pre-RE-PIN is resolved against the committed
  handoff).

## 7. No rig masking

- Python batch diff (c2a25c5..tip) outside `conformance/vectors` + `context/`:
  ONLY the 4 src files of the four bugs + 7 test files +
  `tests/live/test_040_query_completeness_live.py` (offline param-shape
  assertions). `conformance/` code (runner, tests, handoff, harness, scripts,
  justfile) untouched except the 4 referee artifacts.
- TS diff (8fa150d..main) outside `conformance-runner/corpus/`: ONLY
  `corpus.config.json` (sourceCommit bump 70c904dc→700db996), README(s), the
  referee-feed test (pin retirement), and the four twin-retirement src/test
  files. `conformance-runner/src/**`, `scripts/`, `differential/referees/`,
  `vendor/` — ZERO changes.
- TS corpus sync integrity: changed-file set (158) is IDENTICAL to the Python
  re-pin changed set; end state `diff -r` byte-identical to Python
  `conformance/vectors` (extra TS-side files are the 5 contract artifacts +
  api-map + canonical-selftest, each byte-identical to its Python source);
  old-state spot hashes (4 bundles incl. manifest) match Python @ old pin — so
  the TS corpus diff is byte-for-byte the audited re-pin diff.

## 8. Minor observations (non-blocking)

1. `conformance-runner/src/batch-status.ts:74` doc comment still reads
   "TERMINAL STATE … 3,251 PASS / 0 FAIL / 0 UNPORTED (corpus pin `70c904dc`)".
   It is explicitly dated to the B8 gate so it is a justified historical
   record, but it lives in shipped rig source and reads like current state; a
   one-line "re-pinned 700db99 → 3,262 (R10.7 four-bug batch)" addendum would
   prevent future-reader confusion. Cosmetic only.
2. New pin `700db996` is a commit on the local-only Python branch (per the
   LOCAL-COMMITS-ONLY choreography); the pin becomes remotely resolvable only
   after the orchestrator pushes `ts-port/python-bugfix-batch`. Sequencing
   note for the orchestrator, not a defect. (Also: the stray untracked
   `CLAUDE.md` in the TS working tree noted by the implementer is not part of
   any reviewed commit.)
