# Phase-1 Audit — Lens 2: Smoke Test / Judge Validity (D9)

Auditor: independent verification agent (read-only mandate).
Date: 2026-08-15.
Repo: `/Users/jaredmcfarland/Developer/mixpanel-headless`, branch `ts-port/phase1-verification-rig` @ `63db3b08a69afa3aacdc2cac8da23f9db7d313bc`.
Scope: `conformance/smoke/run_smoke.py`, `conformance/smoke/patches/S01..S13.patch`, `conformance/smoke/last-run.json`, runner crash/catch semantics, independent re-execution of control + 5 patches.

Verdict: **PASS with minor findings** — the smoke rig is sound, the recorded PASS is reproducible, and no defect undermines the D9.3 judge-validity claim.

## (a) Critical read of run_smoke.py, the 13 patches, and last-run.json

### Control-run design — VERIFIED
`_execute_one("control", ref_sha, ...)` uses the exact same `_prepare_worktree` path as sabotage runs (same ref, same `/tmp` parent, same `uv sync --all-extras` bootstrap), with the patch step skipped (`run_smoke.py:304-306`). The control is a genuinely identical unpatched worktree — never the developer checkout — matching D9.2's "Control run" clause. Control criterion: `status == "clean"` requires `failing_count == 0` AND a parseable exit-0/1 report; a dirty or errored control fails the whole smoke (`main()`: `passed = control_ok and patches_ok`).

### Bootstrap — VERIFIED
`uv sync --all-extras` runs in every fresh worktree before the runner (`_prepare_worktree`, `run_smoke.py:164-173`), with sync failure/timeout classified as smoke ERROR (never a catch). This closes the D9.2 hazard where 13 freezegun-import crashes could masquerade as 13 catches; the runner CLI additionally fails fast with `runner_crashed` if freezegun is missing (`runner/__main__.py:116-124`).

### cwd-correct uv invocation — VERIFIED
Both `uv sync` and `uv run python -m conformance.runner` execute with `cwd=<worktree>` (`_run(cmd, cwd, ...)`; `_run_runner` passes `worktree` as cwd) and `--vectors <worktree>/conformance/vectors` as an absolute path into the worktree. Library code AND vectors both come from the worktree tree per D9.2 step 4.

### Crash-vs-catch discrimination — VERIFIED (statically and empirically)
- Runner side: exit 0 = all pass, 1 = ≥1 `vector_failed`, 2 = `runner_crashed` (corpus load, missing freezegun, clock setup, harness exception outside vector execution) — `runner/__main__.py`.
- Smoke side: `_classify` returns `status="error"` whenever `error is not None or report is None or exit_code not in (0, 1)`; `caught` requires a parsed report with `failed >= 1` on exit 0/1. A crash therefore cannot be counted as a catch. A non-JSON stdout (e.g., traceback) → parse failure → ERROR, fail-closed.
- Empirical proof: I injected an import-breaking line into `src/mixpanel_headless/_internal/api_client.py` in a throwaway worktree and ran the runner: exit 2, `{"status": "runner_crashed", "failed": 0, ...}` — which `_classify` maps to ERROR, failing the smoke. A crash is demonstrably never a catch.
- Provenance discipline: `last-run.json` is written only on FULL runs (control + all 13), so partial re-runs cannot masquerade as a complete smoke record. My partial re-run printed "partial run — last-run.json NOT written" and left the file untouched (confirmed via `git status`).

### Patch files vs D9.1 table — VERIFIED
All 13 committed patches match the D9.1 design table exactly (S01 `<=0`→`<0`; S02 `fromisoformat`→`pass`; S03 `/segmentation`→`/segment`; S04 us query base →`eu.mixpanel.com`; S05 drop percentile mapping; S06 inverted cursor guard; S07 `"equals": "!="`; S08 `return on`; S09 `" or ".join`; S10 `count / steps[0].count`; S11 empty-cohort `1.0`; S12 `attempt + 1 >= self._max_retries`; S13 `range(1)`). Coverage mapping (request side / payload / validation / transform / multi-request) holds.

### last-run.json — VERIFIED with one caveat (Finding F1)
Recorded run: commit `c0eefab8`, 2026-08-14, control clean 0/2609, all 13 patches caught, result PASS. Caveat: `c0eefab8` is 5 commits behind branch HEAD `63db3b08`. I diffed `c0eefab..HEAD`: it adds only new harness code (oracle_py, fuzz harness, referee, CI yml, smoke artifacts themselves) — **zero changes to `src/`, `conformance/vectors/`, or `conformance/runner/`** — so the recorded results remain representative of HEAD, and my re-run at HEAD reproduced them exactly. Corpus size cross-check: 146 `.jsonl` files × 1 `$bundle` header + 2609 vector lines = 2755 lines on disk = consistent with `total: 2609` in every run.

## (b) Independent re-execution

Full `run_smoke.py` partial invocation at HEAD (`uv run python -m conformance.smoke.run_smoke --patches S04,S06,S08,S10,S11`), fresh worktrees + `uv sync` per run:

| run | my status | my failing | last-run.json | first_failing_id match |
|---|---|---|---|---|
| control | clean | 0 | clean / 0 | — |
| S04 (region table) | caught | 228 | caught / 228 | yes (`bookmarks/api_client.activity_feed/...between_date_range...`) |
| S06 (pagination guard) | caught | 28 | caught / 28 | yes (`pagination/...canonical_query_origin...`) |
| S08 (expression wrap) | caught | 18 | caught / 18 | yes (`segmentation/expressions...backslash_before_quote...`) |
| S10 (funnel transform) | caught | 2 | caught / 2 | yes (`funnels/workspace.funnel/authored-four-step-aggregated-across-dates`) |
| S11 (retention transform) | caught | 2 | caught / 2 | yes (`retention/workspace.retention/authored-empty-cohort-zero-rates`) |

Exact reproduction on all six runs, script exit 0, "smoke result: PASS".

### S10/S11 gap-fill verification — VERIFIED
The D9.3 miss-fill vectors exist on disk (`conformance/vectors/authored/funnels/live-query-transforms.jsonl`: 3 vectors; `.../retention/live-query-transforms.jsonl`: 3 vectors, committed in `c0eefab`). In a manual worktree I applied S10 and S11 individually and inspected the JSON failure reasons:
- S10 → exactly 2 failures, BOTH authored vectors (`authored-four-step-aggregated-across-dates`, `authored-three-step-conversion-rates`), reason type `result mismatch` with divergent step conversion_rates (e.g., expected 0.333… from step-over-step vs patched step-over-first). The third authored funnel vector (`authored-zero-previous-step-count`) correctly does not fire (both formulas agree there).
- S11 → exactly 2 failures, BOTH authored vectors (`authored-empty-cohort-zero-rates`, `authored-mixed-empty-and-live-cohorts`), reason type `result mismatch` on retention arrays (0.0 vs 1.0 for size-0 cohorts).
Because the failing ids are exclusively authored vectors, the original misses were real coverage holes and the gap-fill is both necessary and sufficient — these two patches are held by the authored vectors alone.

### Failure-reason sampling (behavioral, not incidental)
- S04: `interaction[0] request mismatch` — `scheme_host` expected `https://mixpanel.com` got `https://eu.mixpanel.com` (37/67 segmentation vectors red in my filtered run; 228 corpus-wide).
- S06: mix of `result mismatch` (e.g., `[{"id":1}]` instead of 3 pages) and `unexpected error at replay: VectorReplayError: request beyond the recorded interaction sequence` — the transport raises on extra requests, so the inverted guard cannot infinite-loop (my S06 run finished in seconds; sleeps are frozen by the clock shim).
- S10/S11: pure `result mismatch` as above.

## (c) Sabotage quality

All 13 patches are syntactically valid, behavior-only edits to `src/`; none removes or breaks a module-level import:
- S02's `pass` substitution keeps a valid `try:` body (`pass` + `return True`) — `_is_valid_date` degrades to always-True, a verdict flip, not a SyntaxError.
- S10's `steps[0].count` is guarded by the `1.0 if idx == 0 else ...` short-circuit — no IndexError on the first step; divergence is purely numeric and only for funnels ≥3 steps where step-2 count ≠ step-1 count (exactly why the extracted corpus originally missed it).
- S08 leaves `escaped` computed-but-unused — dead code, no runtime effect beyond the intended return change.
- Verdict on weak-sabotage risk: **none of the 13 can be "caught" by an import error** — and even if one were authored that way, an import-time failure produces exit-2 `runner_crashed`, which the smoke classifies as ERROR (fails the smoke for infrastructure reasons), not a catch. Verified empirically in (a).
- Nuance worth recording (Finding F2): exceptions raised *inside* vector execution — including harness-side decode/target-construction errors (`run_vector`'s `except` → "replay infrastructure error inside vector") — count as vector failures, i.e., catches. For src-only sabotage this is correct (a library call raising where a result was recorded IS a behavioral divergence, and a TS port would diff red the same way), but a latent harness bug that throws per-vector would inflate catch counts rather than surface as ERROR. Mitigated by the clean control (any unconditional harness throw would dirty the control) — residual risk is a patch-interaction-only harness bug, which none of the 13 exhibits (all sampled reasons are genuine diffs).

## (d) Worktree cleanup

- `run_smoke.py` removes each worktree in a `finally` block (`--keep-worktrees` off by default) and prunes registrations; after my full re-run, `/tmp` contains no `mp-smoke-*` directories.
- I created one manual worktree (`/tmp/mp-audit-manual`) for reason-level inspection and removed + pruned it.
- `git worktree list` after cleanup shows the main tree plus two NON-smoke worktrees that predate/parallel this audit and are not mine to remove: `/Users/jaredmcfarland/Developer/mixpanel-headless-pr195` (branch `pr195-fixes`, pre-existing developer worktree) and `/private/tmp/audit-sabotage` (detached at the same HEAD — consistent with a concurrent audit lens; left in place). Neither is a smoke-rig leftover (Finding F3).

## Read-only compliance

No tracked file was modified by this audit (`git status` shows only pre-existing untracked/modified paths; `conformance/smoke/last-run.json` untouched — partial runs never write it). Note for the orchestrator: `context/typescript-port-rulebook.md` carries a pre-existing uncommitted +9-line local modification that was present before/independent of this audit (Finding F4 — hygiene observation only).

## Findings

| # | Severity | Finding |
|---|---|---|
| F1 | minor | `last-run.json` is pinned to `c0eefab8` (5 commits behind rig HEAD). Validated harmless — no `src/`/vectors/runner changes since — and reproduced at HEAD, but D9.3's release-gate wording implies the final gate declaration should carry a full run at the gate SHA. |
| F2 | minor | In-vector exceptions (library OR harness decode/construction) classify as `vector_failed` = catch; only pre/outside-vector failures are `runner_crashed`. Correct for src-only sabotage and mitigated by the clean control, but a patch-triggered per-vector harness bug would count as a catch. Documented behavior (`execute.py:run_vector` docstring), no action required for the 13 fixed patches (all sampled reasons are behavioral diffs). |
| F3 | minor | Repo carries two non-smoke worktrees (`mixpanel-headless-pr195`, `/private/tmp/audit-sabotage`); neither is smoke-rig debris. Smoke-owned worktrees clean up correctly. |
| F4 | minor | Pre-existing uncommitted +9-line modification to tracked `context/typescript-port-rulebook.md` in the working tree (not made by this audit; flagged for hygiene before gate declaration). |

## Checks executed (all via fresh worktrees / repo-root uv)

1. `run_smoke.py --patches S04,S06,S08,S10,S11` (control + 5 sabotage, full corpus each) → PASS, exact match to last-run.json on status, counts, and first_failing_id.
2. Manual worktree, S10 with `--filter 'funnels/*'` → 2/120 failed, both authored, `result mismatch`.
3. Manual worktree, S11 with `--filter 'retention/*'` → 2/79 failed, both authored, `result mismatch`.
4. Manual worktree, S04 with `--filter 'segmentation/*'` → 37/67 failed, `scheme_host` request mismatch.
5. Manual worktree, S06 with `--filter 'pagination/*'` → 28/39 failed, result mismatches + `VectorReplayError` extra-request.
6. Crash simulation (import-breaking edit) → runner exit 2 `runner_crashed`, `failed: 0` → smoke would classify ERROR, not catch.
7. `git diff c0eefab..HEAD --stat` → no `src/`, vector, or runner changes since the recorded run.
8. Patch-by-patch diff vs D9.1 table → 13/13 match.
9. Corpus arithmetic: 2755 jsonl lines − 146 `$bundle` headers = 2609 = reported total.
10. Cleanup: no `mp-smoke-*`/`mp-audit-*` under `/tmp`; own worktree removed and pruned; `last-run.json` and all tracked files unmodified.
