# AD-10 — Independent mini-audit of the Phase-1 addendum

- **Auditor**: AD-10 (independent re-execution; no reliance on prior task reports)
- **Date**: 2026-08-15
- **Audited HEAD**: `6b821af` on `ts-port/phase1-addendum` (base: `852d718` on `ts-port/phase1-verification-rig`)
- **TS repo**: `/Users/jaredmcfarland/Developer/mixpanel-headless-ts` @ `9ad06d6` (branch `main`)
- **Method**: every claim below was re-executed live during this audit — `just check`, the corpus runner CLI, a full 14-patch smoke re-run at HEAD, vector sampling with live guard execution, PII greps, `npm run check`, the TS conformance CLI, and remote/porcelain inspection. No verdict was copied from a prior report.

## Verdict: PASS (7/7 items)

| Item | Check | Result |
|------|-------|--------|
| (a) | `just check` green at HEAD; src/ diff confined to design-named files; CLAUDE.md / .claude / pyproject untouched | **PASS** |
| (b) | Corpus runner 100 % at HEAD; vector count vs 3,000 target | **PASS** — 3,155 / 3,155, `status: ok` |
| (c) | Smoke 14/14 at current-HEAD provenance | **PASS** — re-run live at `6b821af`: control clean, 14/14 caught |
| (d) | 10 sampled new validation-error vectors: codes asserted, no message text | **PASS** (message-free property verified over all 477 new error vectors, not just 10) |
| (e) | Storybook vectors scrubbed (no `@mixpanel.com`, `3018488`, employee-email fragments) | **PASS** — zero hits |
| (f) | TS `npm run check` green; conformance CLI zero FAIL; snapshot pin matches Python manifest | **PASS** |
| (g) | No pushes anywhere; analytics porcelain clean | **PASS** |

---

## (a) `just check` + change-scope containment — PASS

- `just check` at HEAD `6b821af`: **exit 0** (lint, fmt-check, mypy --strict, test-cov ≥ 90 %, conformance corpus 3,155 passed in 2.33 s, `uv build` succeeded).
- `git diff --stat 852d718..HEAD -- src/` touches exactly 9 files:
  `__init__.py`, `exceptions.py`, `types.py`, `workspace.py`,
  `_internal/api_client.py`, `_internal/bookmark_builders.py`,
  `_internal/segfilter.py`, `_internal/query/user_builders.py`,
  and the new `_internal/response_validation.py`.
  - The first 8 are named verbatim in the coding-pass design's file table / §3 batch lists.
  - `response_validation.py` is the design §1.7 mandate realized: "one private helper (e.g. `_validate_response_model(...)`)" applied to *both* `workspace.py` and `api_client.py` response seams — a shared private module is the only placement that serves both files. Judged **in scope**.
  - `expressions.py` / `transforms.py` (design: 0 sites) are untouched, as required.
- `git diff 852d718..HEAD -- CLAUDE.md .claude pyproject.toml`: **empty**. Full changed-path list contains nothing outside `src/`, `tests/`, `conformance/`, `context/`. All changed test files map to the guarded modules (incl. `tests/unit/_internal/test_response_validation.py`, `test_workspace_crud_edge.py`, `test_types_replay_*.py` — the files the design names for TDD).

## (b) Corpus runner at HEAD — PASS; count stated plainly

```
uv run python -m conformance.runner --vectors conformance/vectors --report json
→ {"status": "ok", "total": 3155, "passed": 3155, "runtime_seconds": 1.4}
```

- **Total vector count: 3,155 — above the 3,000 target by 155.**
- Accounting: manifest `counts.total` = 3,007 **extracted** vectors (manifest covers extraction only) + 148 **authored** vectors on disk = 3,155, matching both the runner total and an independent line-count of every `*.jsonl` (bundle headers excluded).
- Kind split at HEAD: 1,803 builder / 1,212 wire / 75 parse / 65 validation-error.

## (c) Smoke: 14/14 at current-HEAD provenance — PASS

- The committed `conformance/smoke/last-run.json` records provenance commit `1c63780` (14/14 caught, control clean, no infrastructure-only catches). The only commits after it (`2f31a35`, `a40f3e9`, `6b821af`) touch `referee_bookmark_parser/`, `conformance/tests/`, and docs — no smoke-relevant surface (src/, vectors/, runner/, smoke patches).
- Verified by running, not by reading: this audit re-ran the **full** smoke (`uv run python conformance/smoke/run_smoke.py`, worktrees at HEAD `6b821af`): **control clean (3,155/3,155), all 14 patches S01–S14 caught, zero infrastructure-only catches** — identical failing-vector counts to the committed run (S01:13, S02:2, S03:10, S04:236, S05:4, S06:28, S07:7, S08:18, S09:8, S10:2, S11:2, S12:8, S13:21, S14:6). The regenerated report's `commit` field confirmed `6b821af…` before restore.
- After verification the working-tree `last-run.json` was restored to the committed artifact (`git checkout --`), since AD-10 is authorized to write only this AUDIT.md. Re-run details preserved in `ad10-scratch.md` (untracked working notes).

## (d) Sample of new validation-error vectors — PASS

- New-vs-base diff: **477** vectors with `expect.error` were added between `852d718` and HEAD.
- Global property check over **all 477** (stronger than the 10-sample ask): every `expect.error` carries `class` + `code`; **zero** contain `message`, `message_pattern`, or any message-text key.
- Random sample of 10 (seed 4210), each cross-checked against its source test and src raise site:

| Code | Source test (exists, re-located) | src site |
|---|---|---|
| `V13_METRIC_MATH_PROPERTY` | `tests/unit/test_query_types.py` (asserts code) | `_internal/validation.py:2207` |
| `EV1_EMPTY_EVENT` | `tests/test_validation_funnel.py` (legacy `match=` test) | `types.py:9119` |
| `CD6_DATE_ORDER` | `tests/unit/test_cohort_definition.py` (asserts code) | `types.py:8854` |
| `CM2_COHORT_NAME_EMPTY` | `tests/test_types_cohort_behaviors.py` (asserts code) | `types.py:9156` (family f-string helper) |
| `CM5_INLINE_COHORT_METRIC` | `tests/test_build_cohort_params.py` (legacy `match=` test) | `_internal/validation.py:1978` |
| `LC8_NESTED_LIST_CONTAINS` | `tests/unit/test_query_types.py` (asserts code) | `types.py:8258` |
| `CD9_EMPTY_CRITERIA` | `tests/unit/test_cohort_definition.py` (asserts code) | `types.py:9229` |
| `FF4_DATE_RANGE_PAIR` | `tests/unit/test_query_types.py` (asserts code) | `types.py:9672` |
| `CD5_TO_REQUIRES_FROM` | `tests/unit/test_cohort_definition.py` (asserts code) | `types.py:8837` |
| `FL4_REVERSE_RANGE` | `tests/test_types_flow.py` (asserts code) | `_internal/validation.py:1642` |

- The two legacy message-matching tests (EV1, CM5) predate the coding pass; their **vectors** still assert class+code only (recorded at the seam). Both guards were additionally re-executed live in this audit: `Exclusion("")` → `ParamValidationError` `code="EV1_EMPTY_EVENT"`; `CohortMetric(<inline CohortDefinition>, ...)` → `ParamValidationError` `code="CM5_INLINE_COHORT_METRIC"`. (And the corpus runner independently re-executes all 477 — see (b).)

## (e) Storybook vector scrubbing — PASS

69 storybook parse vectors present under `conformance/vectors/authored/parse/storybook/` (matches the AD-5 "69 emitted" count). Greps over the entire committed `conformance/vectors/` tree, each returning **zero hits** (grep exit 1):

- `@mixpanel.com` — 0
- `3018488` (project id) — 0
- `alix.becker`, `areeb.iqbal`, `mack.duan`, `pablo.fierro` (the parse-fixtures.md employee-email fragments) — 0
- `3536632` (workspace id, extra check beyond the ask) — 0

## (f) TS repo — PASS

- `npm run check`: **exit 0** (typecheck, lint, fmt:check, vitest: 24 files, 386 passed / 3,113 skipped-unported, browser-bundle smoke OK).
- Conformance CLI (`npm run conformance`): `{"total": 3155, "passed": 42, "failed": 0, "skipped_unported": 3113}` — **zero FAIL** (the 3,113 skips are declared-unported targets at this phase, not failures).
- Snapshot pin: `conformance-runner/corpus.config.json` `sourceCommit = d5627564d7e5a6711c4980f72187563f27e4c7f7` **==** Python `conformance/vectors/manifest.json` `source_commit`. (`d562756` is the working-tree commit the AD-6 re-extraction ran at; the vectors were committed one commit later at `57cf3f6` — the pin correctly records extraction provenance.)
- Content parity verified beyond the pin: the sha256-of-sha256s over every `*.jsonl` is **identical** on both sides (`e921be64…`), and `manifest.json` / `api-index.json` are byte-identical.

## (g) No pushes; analytics clean — PASS

- Python repo: remotes exist (`origin`, `gslopez`) but `git branch -r` lists **no** `ts-port/*` remote branches, and neither local `ts-port/phase1-verification-rig` nor `ts-port/phase1-addendum` has an upstream (`branch -vv`). Local-only confirmed.
- TS repo: `git remote -v` is **empty** (remoteless), branch `main`, porcelain clean.
- `/Users/jaredmcfarland/Developer/analytics`: `git status --porcelain` → **0 lines** (clean).

---

## Notes / observations (non-blocking)

1. `conformance/vectors/manifest.json` `counts.total` (3,007) intentionally covers extracted vectors only; authored vectors (148) are outside the manifest. Anyone comparing "manifest total" to "runner total" (3,155) should use the accounting in (b).
2. Untracked scratch files (`ad6/ad7/ad8/ad10-scratch.md`) sit in `context/phase1/addendum/` — working notes, uncommitted by design; harmless.
3. The open R7 frequency-filter escalation (server rejects the library clause shape; probe committed at `6b821af`) is a known, documented referee finding — outside this audit's pass/fail scope and correctly quarantined (TS stays byte-for-byte pending fix + re-extraction).
