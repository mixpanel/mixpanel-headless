# Independent Audit — Phase-1 Python Verification Rig (LENS 1)

- Auditor: independent (re-executed every check; no build-agent claim trusted).
- Date: 2026-08-15
- Repo: /Users/jaredmcfarland/Developer/mixpanel-headless
- Branch: `ts-port/phase1-verification-rig` @ 63db3b0 (base `fix/latent-bugs-stress-test` @ 5269674 — confirmed 52696743b913a0c4c152deb48af987ae412b5aee)
- Pre-existing working-tree state noted (NOT touched by this audit): modified `context/typescript-port-rulebook.md` (+9 lines, uncommitted) and untracked `context/phase1/{bug-reports,design/escalation-resolutions.md,pr6-notes.md}`, `context/typescript-port-*` files.
- Audit writes: this file only (plus scratch under /tmp: `audit-re-extract`, `audit-re-extract-perturbed`, throwaway worktree `audit-sabotage`, removed after use).

## (a) Corpus runner — VERIFIED, 100% pass, totals reconcile

Both harnesses re-run by the auditor at HEAD (63db3b0):

| Harness | Result | Runtime |
|---|---|---|
| `uv run pytest conformance/runner -o addopts="" -q` | **2609 passed, 0 failed** | 3.10 s reported by pytest |
| `uv run python -m conformance.runner --vectors conformance/vectors --report json` | `{"status":"ok","total":2609,"passed":2609,"failed":0}` | 1.071 s (report), 1.2 s wall |

Reconciliation against `conformance/vectors/manifest.json` (counts.total = **2530**):

- Non-authored bundles: 137 `*.jsonl` files, 2667 lines − 137 `$bundle` header lines = **2530** ✓ (matches manifest exactly; by_capability sums to 2530; by_kind 1302 builder + 64 validation-error + 1164 wire = 2530 ✓).
- Authored bundles (`authored/**`, outside manifest scope by design): 9 files, 88 lines − 9 headers = **79** vectors.
- 2530 + 79 = **2609** = both harness totals ✓. Loader cross-check (`load_vectors`) independently returned 2609 with kinds `{builder: 1361, wire: 1178, validation-error: 64, parse: 6}`; authored dir contributes 79.
- `enums/bookmark_enums.json` is not a vector (loader walks `*.jsonl` only) — an aux snapshot, consistent with the record README ("record mode never emits authored/enums").

## (b) Non-tautology — VERIFIED by code-path reading AND live sabotage

### Code-path reading (5 vectors)

Runner execution (`conformance/runner/execute.py`) never compares recording-to-recording: wire vectors rebuild a real library client around `VectorTransport` (canned responses only), builders resolve through the same registry the recorder used.

1. WIRE `segmentation/api_client.segmentation/test_api_client-testratelimiting-test_successful_response_after_retry`: 3 recorded interactions (429/429/200). Path: `_execute_wire_call` prefix `api_client` → `_ReplayContext.get_client()` → `targets.make_api_client` constructs a real `mixpanel_headless._internal.api_client.MixpanelAPIClient` from the vector session over `VectorTransport` → `getattr(client, "segmentation")(**decoded)` (execute.py:456). Retry loop, param defaults (`unit=day`, `type=general`), `query_origin` injection, and Basic-auth header are all computed live by src/ and diffed against the recorded requests (`_diff_interactions`, incl. never-fired/extra-request assertions).
2. WIRE `pagination/pagination.paginate_all/...` (test_pagination.py bundle): prefix `pagination` → `resolve_callable(REGISTRY_BY_API[api])` → real paginator with the replay client prepended (execute.py:459-472). Decisive detail: `call.input` carries `params.query_origin="spoofed-by-caller"` while the recorded request expects `query_origin="mixpanel-headless"` — only live library overwrite behavior can pass this vector.
3. WIRE `entities/workspace.create_dashboard/...`: prefix `workspace` → `get_workspace()` → `targets.make_workspace` builds a real `Workspace` facade (two-session pattern, D5.1); the POST `json_body {"title":"New Dashboard"}` is serialized live from the `$type`-decoded `CreateDashboardParams` and diffed against the recording.
4. BUILDER (validation-error) `validation/validation.validate_retention_args/test_validation_cohort-...-test_mixed_cohort_and_groupby_returns_cb3_error`: registry target `mixpanel_headless._internal.validation` (real src function); `expect.output` diffed canonically.
5. BUILDER `bookmarks/bookmark_builders.build_time_section/test_bookmark_builders-testbuildtimesection-test_absolute_range_from_and_to`: registry.py:240-241 targets `mixpanel_headless._internal.bookmark_builders:build_time_section`; output `[{"dateRangeType":"between",...}]` recomputed live.

### Empirical sabotage (throwaway worktree /tmp/audit-sabotage @ HEAD, own venv; removed afterward)

- Baseline (unmodified): `--filter 'segmentation/*'` → 67/67 pass.
- Sabotage 1 (wire seam): `client_metadata.py QUERY_ORIGIN "mixpanel-headless" → "sabotaged"` → segmentation **37/67 FAIL** (`status: vector_failed`), request-param diffs.
- Sabotage 2 (builder seam): `validation.py CB3_RETENTION_MIXED_BREAKDOWN → CB3_SABOTAGED` → retention 26/79 FAIL; `--filter '*cb3*'` shows exact output mismatches (`expected ...CB3_RETENTION_MIXED_BREAKDOWN got ...CB3_SABOTAGED`).
- Bonus taxonomy check: running the CLI without `freezegun` synced yields `status: runner_crashed` exit-2 with a precise message (D9.3 crash-is-never-a-catch honored).

Verdict: the corpus genuinely executes src/ from `call.input`; it is not tautological.

## (c) Drift determinism — VERIFIED byte-clean, and the diff tool is sensitive

- Re-extracted the full corpus to `/tmp/audit-re-extract` with the committed manifest's own stamps injected (`--mp-record-date=2026-08-14 --mp-record-commit=5269674...`, `-o addopts="" -m "not live"` + empty `exclusions.args`), exactly the CI D8 invocation. Record run: **6768 passed, 1 skipped, 556 deselected** (matches the ledger's record-run line).
- `uv run python -m conformance.record.diff /tmp/audit-re-extract conformance/vectors` → **"drift check: CLEAN (byte-identical within D8 scope)", exit 0**.
- Direct byte check: `cmp` on re-extracted vs committed `manifest.json` → identical.
- Tool-sensitivity control: perturbed one vector byte in a copy → diff reports `[vector_bytes_differ]` naming the exact bundle+vector id, exit 1. The CLEAN verdict is therefore meaningful, not a no-op.

## (d) Repo standards at HEAD

- `just check` (lint, fmt-check, typecheck, docstring-cov, test-cov, conformance, build): re-run by auditor — see result line below.
- mypy strict DOES cover conformance/: `just typecheck` = `mypy src/ tests/ conformance/`; `[tool.mypy] strict = true` with no relaxing override for `conformance.*` (only `tests.*` relaxes `disallow_untyped_defs`). CI additionally runs `mypy conformance/` in the conformance job.
- **GAP vs D17 (finding F1): `docstring-cov` does NOT cover conformance/.** phase1-design.md D17 item 3 says verbatim: "Add a third line `uv run interrogate conformance/ --fail-under=95` to the recipe". The justfile recipe still runs only `interrogate src/` + `interrogate tests/ --fail-under=95`.
- **GAP vs D17 (finding F2): `just lint`/`fmt-check` are path-scoped to `src/ tests/`** — D17 item 2's claim that repo ruff config "targets the whole tree" so `just lint`/`fmt` cover conformance/ "automatically" is false as implemented. Partial mitigation: the pre-commit ruff hooks run per changed file (so conformance files ARE ruff-checked at commit time when hooks are installed).
- Mitigating measurement (auditor-run): current conformance/ code passes anyway — `ruff check conformance/` all clean, `ruff format --check` 45/45 formatted, `interrogate conformance/ --fail-under=95` = **100.0%** (619/619 documented). The gaps are gate gaps (future regressions unenforced), not present violations.
- CI conformance job (`.github/workflows/ci.yml`): mypy conformance/ + tooling tests + corpus runner + D8 drift re-extraction with manifest-stamped injection — matches design; path filters include `conformance/**`, `pyproject.toml`, `justfile`, `.github/**`.
- `just check` result: **PASS** (all seven recipes green; see checks table in the orchestrator report; run completed 2026-08-15 on this machine).

## (e) Commit hygiene — VERIFIED

- `git log fix/latent-bugs-stress-test..HEAD --oneline` = 17 commits. D16's 10-line sketch is refined by D18's PR-1..PR-11 breakdown, and all 17 map to it in order, with fix/regeneration/generated-results commits separated from hand-written code exactly as D16's last rule requires:
  - PR-1 4f885f4 scaffold+schema+tooling (also committed the previously-untracked `context/typescript-port-*` artifacts, per D16 commit-1 note — verified now tracked); PR-2 b5cb008 record plugin; PR-3 055a420 registry+codecs; PR-4 293f5de canonicalizer+selftest; PR-5 625fab8 extractor fixes / 4debd2d first extraction (generated) / 953b0f7 ledger+audit; PR-6 4eb0b9f pipeline fixes / 9961fbb re-extraction (generated) / 33f5973 runner+CLI; PR-7 e73f303 authored seeds / c0eefab transform-vector miss fill; PR-8 6400311 smoke; PR-9 8e46788 CI; PR-10 a5a6eb7 oracle-py+fuzz; PR-11/D15b 906486e referee harness / 63db3b0 handoff results (generated).
- `git diff 5269674..HEAD --stat -- src/ tests/ CLAUDE.md .claude/` → **EMPTY** ✓. The rig touched no library code, no tests, no instructions. (Repo-level shared-file edits are confined to `justfile`, `pyproject.toml`, `.github/workflows/ci.yml`, per D17/PR-1/PR-9 scope.)
- **Observation (finding F4): an UNCOMMITTED +9-line edit to tracked `context/typescript-port-rulebook.md` sits in the working tree** (adds process rule R10.13 "no xhigh workflow agents"). Pre-existing before this audit's first command; not the auditor's. It is process-doc-only (no code effect), but the design-of-record artifact chain is not fully committed — the orchestrator should commit or discard it deliberately.

## (f) PR-5 shortfall reporting — DOCUMENTED, with one staleness defect

- `conformance/record/EXTRACTION-LEDGER.md` exists; every D10 line is reproduced with estimate-vs-actual and reconciliations; the miss is stated in bold, not papered over: "Actual extracted total: 2,536 — a shortfall of 464 against the 3,000 target… The corpus is the honest maximum the suite supports under the D10 rules."
- **Finding F3 (staleness): the ledger's headline counts no longer match the committed manifest.** Ledger says total 2,536 / wire 1,170 / entities 587 / replays 35 / unserializable_input 19; committed manifest says total **2,530** / wire 1,164 / entities 582 / replays 34 / unserializable_input **25**. Cause: commit 9961fbb ("re-extraction — post-PR-6 pipeline fixes") dropped 6 mock/stub-dependent captures into `unserializable_input` (1 ReplaysService re-sign + 5 business-context `_me_service` stubs) and is fully documented in that commit message — but the ledger file was not updated. The ledger does carry the disclaimer "`manifest.json` is authoritative; this table is a prose snapshot", so the audit trail is recoverable, yet the file a reader is pointed at for "the shortfall" now understates it (real shortfall vs 3,000 target is **470**, not 464).
- Denominator honesty checks re-verified by auditor: record run totals (6,768/1/556) reproduced exactly in the (c) re-extraction; exclusion_details in manifest list concrete node ids per category; `exclusions.args` is intentionally empty as documented.

## Findings summary

| # | Severity | Finding |
|---|---|---|
| F1 | minor | D17-required `interrogate conformance/ --fail-under=95` line missing from `just docstring-cov` (code currently measures 100%, so no present violation — gate gap only). |
| F2 | minor | `just lint`/`fmt-check` scoped to `src/ tests/`; conformance/ ruff enforcement rests on pre-commit per-file hooks + current clean state, contradicting D17's "whole tree" rationale. |
| F3 | minor | EXTRACTION-LEDGER.md headline counts stale after the 9961fbb re-extraction (2,536 vs committed 2,530; unserializable_input 19 vs 25; true target shortfall 470). Documented in the commit message but not in the file of record. |
| F4 | minor | Uncommitted +9-line working-tree edit to tracked `context/typescript-port-rulebook.md` (R10.13 process rule) — design-of-record chain not fully committed; commit or discard deliberately. |

No blocker or major findings. All executable claims reproduced: 2609/2609 pass on both harnesses, byte-clean drift, sabotage-sensitive corpus, empty library-code diff.
