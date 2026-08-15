# P2-1 working notes (running)
## Deliverables checklist
- [ ] Branch ts-port/phase2-contract-support off ts-port/phase1-addendum HEAD (verify parentage)
- [ ] conformance/contract/{__init__,generate_contract}.py + tests
- [ ] Artifacts: error-codes.json, literal-aliases.json, tag-universe.json, model-coverage.json (byte-deterministic re-run)
- [ ] Recorder registry entries + recorded vectors for: types.FunnelStep, types.RetentionEvent, types.CohortCriteria.did_not_do_event, .property_is_set, .property_is_not_set (+ guard-failure cases)
- [ ] Re-extract + re-pin snapshot SHA (Risk #3); api-index types.* count = 44
- [ ] Python runner + D9 drift check green on branch
- [ ] TS: extend scripts/sync-corpus.sh to copy conformance/contract/*.json -> conformance-runner/corpus/contract/; run; re-pin snapshot; one TS commit
- [ ] just check green (or documented conformance-scoped equivalent); one Python commit
## Facts
- Registry: add 4 tuples to _CODED_GUARD_TARGETS (FunnelStep/funnels, RetentionEvent/retention, CohortCriteria.property_is_set + property_is_not_set/cohorts); did_not_do_event already registered.
- Vector mechanism: record run = `pytest tests ... $(cat conformance/record/exclusions.args)` (justfile + ci.yml both). exclusions.args is under conformance/ -> add path `conformance/tests/test_coverage_cases.py` there; new pytest file with guard-failure cases produces builder error vectors via error_only entries. Update record/README + ledger.
- Codes: FunnelStep/RetentionEvent -> EV1_EMPTY_EVENT / EV2_CONTROL_CHAR_EVENT (_validate_event_name, control-char re at types.py:9076). did_not_do_event -> CD4_EMPTY_EVENT, CD3_*, CD5_*; property_is_set/not_set -> CD7_EMPTY_PROPERTY (delegates to has_property; inner suppressed by re-entrancy).
- api-index built from extracted captures only (emit.py:1430); types.* now 39 -> need 44.
- error-codes.json default codes: use signature `code` default when present else instantiate with annotation-driven dummies (str->x, int->1, list/Sequence->[], Literal->first member). 28 classes confirmed instantiable.
- Built-in codec tags: datetime,date,SecretStr,bytes,callback,float (hardcoded ifs in codecs.py) — generator declares constant + behavioral cross-check test.
- canonical_json lives in conformance/record/emit.py:222.
- Registry test to extend: conformance/tests/test_registry.py::test_coded_guard_entries_registered_and_resolvable expected tuple.
- Extraction stamps: commit code first (commit1), extract with --mp-record-date=2026-08-15 --mp-record-commit=<commit1 sha>, then commit2 = vectors+artifacts+ledger. AD-6 precedent.
## Progress
- Branch ts-port/phase2-contract-support @ c334b50 parent. Commit1 (code) = 0cc33b0ecc750acbe4929408d00542db9d555d2a.
- Extraction done: 3,031 vectors / 157 bundles / 7,143 passed. +25 ids / -1 id (has_property->property_is_set reseat). api-index types.* = 44. builder 1768 (+24).
- Runner: 3,179/3,179 pass. Artifacts generated with commit1 SHA; double-run cmp identical.
- conformance tests 384 pass; mypy/ruff/format/interrogate green.
- Ledger section added (P2-1 re-extraction).
- Drift check running in background (bib6vwfyn) -> /tmp/p21-drift.log (expect EXIT=0 + DIFF_EXIT=0).
- TS: sync-corpus.sh extended (contract/*.json -> corpus/contract/, RIG_BRANCH default -> phase2-contract-support, artifact presence gate). TS baseline npm test green (3155 corpus: 42 PASS/3113 skip, 386 passed).
## Remaining
- Wait drift -> commit2 (vectors+artifacts+ledger+notes?) -> smoke (background, full 14-patch) -> TS: pin corpus.config.json to 0cc33b0..., run sync, npm test (expect 3179 corpus tests), npm run check, one TS commit.
- Commit2 (vectors+artifacts+ledger) = 5f5f2c02587dbd6494325242a12aac4fc3861f6c.
- Drift check: CLEAN both directions (p21-drift.log EXIT=0 DIFF_EXIT=0).
- TS commit da3fe5c: sync-corpus extension + pin 0cc33b0e + snapshot (3179 corpus vectors; 42 PASS unchanged) + naming-exceptions 3 rows (generator flagged; C7 verify-then-add) + api-map.gen regen (407 entries). npm run check EXIT=0.
- Smoke (D9 full 14-patch) running; will commit conformance/smoke/last-run.json on PASS. Then just check.
- Smoke: PASS (control clean + S01..S14 all caught); commit 9d2e71d (last-run.json).
- Oracle path: all 5 new apis resolve via REGISTRY_BY_API (oracle_py/server.py uses the same table).
- TS naming-exceptions: generator flagged the 3 class-qualified factory names (C7 verify-then-add rule) -> 3 rows added, api-map.gen regenerated (407 entries).
- just check running (bhalydi20 -> /tmp/p21-justcheck.log).
