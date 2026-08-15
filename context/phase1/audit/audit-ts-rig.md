# Lens 4 Audit — TS Rig + Phase-1 TS Gate

Auditor: independent verification agent (re-executed everything; trusted no report).
Date: 2026-08-15 (checks began 2026-08-14 ~23:58 local).
TS repo: /Users/jaredmcfarland/Developer/mixpanel-headless-ts @ `8110cea` (branch `main`, working tree clean before and after audit).
Python repo: /Users/jaredmcfarland/Developer/mixpanel-headless @ `63db3b0` (branch `ts-port/phase1-verification-rig`).
Design of record: `context/phase1/design/phase1-design.md` D11–D16; gate record: `conformance-runner/GATE.md`.

## Verdict: PASS (with 3 minor findings)

All six D13 gate criteria re-verified — five by full re-execution (including both
deliberate-break sabotage probes, which reproduced GATE.md's failure sets exactly),
one (criterion 1, Python side) by re-running the compat filter. `npm run check` is
fully green at HEAD. No blocker or major findings.

## (a) `npm run check` at HEAD — PASS

- Command: `npm run check` (typecheck all workspaces → eslint → prettier --check →
  vitest run → browser-bundle smoke). Exit 0.
- Vitest: 24 files, **383 passed | 2561 skipped (2944 total)** — includes
  `conformance-runner/test/corpus.test.ts` (2603 tests, 42 executed, 2561 skipped
  UNPORTED), matching GATE.md criterion 2's vitest claim.
- Browser-bundle smoke exists and ran: `scripts/browser-smoke.mjs` →
  `browser-bundle smoke OK: core bundled for browser (18051 bytes)` (esbuild
  `--platform=browser` of packages/core, wired into `check` per D11).
- **R9.1 core-purity boundary probe (re-executed)**: wrote a scratch (untracked)
  file `packages/core/src/__audit_purity_probe.ts` containing
  `import fs from "node:fs"` and a `process.env` read; `npx eslint` flagged BOTH:
  - `1:1 error 'node:fs' import is restricted ... (no-restricted-imports)`
  - `2:44 error Unexpected use of 'process' ... (no-restricted-globals)`
  - exit code 1. Probe file deleted; `git status --porcelain` empty afterward.
- eslint.config.js scopes the boundary to `packages/core/**/*.ts`: restricted
  paths `fs`/`path`/`os`/`undici`, pattern `node:*`, plus `process` global — as
  specified by D11/R9.1.

## (b) Conformance CLI over committed snapshot — PASS

- `npm run conformance -- --report json` (full corpus):
  `{"total": 2603, "passed": 42, "failed": 0, "skipped_unported": 2561, "failures": []}`
  → **42 PASS / 2561 UNPORTED / 0 FAIL / 0 UNMAPPED_API** (UNMAPPED_API is
  always-failing per D12; the empty `failures` array proves zero).
- `--filter "compat/"` → 42/42; `--filter "compat/wirestub"` → 8/8. The 42 = 34
  pythoncompat builder vectors + 8 wirestub wire vectors (file line counts: 35 and
  9 incl. one `$bundle` header each).
- **Corpus pin verified three ways**: `conformance-runner/corpus.config.json`
  `sourceCommit` = TS snapshot `corpus/manifest.json` `source_commit` = Python
  `conformance/vectors/manifest.json` `source_commit` =
  `52696743b913a0c4c152deb48af987ae412b5aee`. The CLI banner echoes
  `corpus @ 52696743b913`.
- **Snapshot fidelity**: `diff -rq conformance-runner/corpus ↔ conformance/vectors`
  shows byte-identical content except (1) snapshot-only `canonical-selftest.json`
  and `typescript-port-api-map.json` (copied by `scripts/sync-corpus.sh` per D12),
  and (2) Python-only `authored/funnels/` + `authored/retention/` — the 6
  `live-query-transforms` vectors committed in rig `c0eefab` AFTER the snapshot
  point `e73f303` (GATE.md documents exactly this). See finding F1.
- Loader drift protection is real: `loader.ts` raises `CorpusIntegrityError` on
  `manifest.source_commit` ≠ pinned `sourceCommit`, per-bundle commit/line-count
  checks, corpus-unique vector ids.

## (c) Six D13 gate criteria — ALL RE-VERIFIED

1. **Python compat vectors** — re-ran
   `uv run python -m conformance.runner --vectors conformance/vectors --filter 'compat/*' --report json`
   → `total: 42, passed: 42, status: ok`. Matches GATE.md. (GATE.md's full-corpus
   2609 control number was not re-run — full-corpus Python runs are Lens 1/2
   scope; the 2609 = 2603 + 6 arithmetic is consistent with the `c0eefab`
   vectors observed in (b).)
2. **TS compat replay** — 42/42 via CLI and via the vitest corpus suite (42
   executed / 2561 skipped inside `npm run check`). Matches GATE.md.
3. **Canonicalizer selftests, both languages** — re-executed:
   - Python: `uv run pytest conformance/tests/test_canonical_selftest.py -q` → **61 passed**.
   - TS: `npx vitest run conformance-runner/test/canonical-selftest.test.ts` → **59 passed**.
   - Contract files byte-identical: sha256 of
     `conformance-runner/corpus/canonical-selftest.json` equals
     `conformance/schema/canonical-selftest.json`.
4. **Deliberate break, builder path (re-executed)** — removed the sign-aware
   branch of `packages/core/src/compat/zfill.ts` (naive `padding + value`).
   `--filter "compat/compat.zfill"` → **12 vectors: 7 passed, 5 failed**, all
   `FAIL_OUTPUT`, ids exactly matching GATE.md (`authored-neg-42-width-5`,
   `authored-neg-one-width-3`, `authored-plus-seven-width-3`,
   `authored-sign-only-minus`, `authored-sign-only-plus`; e.g.
   `output "0-1" != expected "-01"`). Reverted via `git checkout`;
   `git status --porcelain` empty; rerun → 12/12 green.
5. **Wire-stub vectors through VectorFetch** — the 8 `wirestub.*` vectors pass
   standalone (`--filter "compat/wirestub"` → 8/8) and inside the 42.
6. **Deliberate break, wire path (re-executed)** — applied both GATE.md
   sabotages to `conformance-runner/src/wirestub.ts` (drop first query param;
   swallow fetch rejection → `{status: 0, body: null}`). Result: **8 vectors:
   5 passed, 3 failed** — `authored-params-absent` FAIL_REQUEST
   (`params null != recorded {"unit":"day"}`), `authored-single-interaction`
   FAIL_REQUEST (`params null != recorded {"q":"1"}`),
   `authored-transport-error` FAIL_ERROR (`expected raise {"class":"ConnectError"}
   but the call returned`) — byte-for-byte the GATE.md failure set. Reverted;
   tree clean; `compat/` rerun → 42/42.

## (d) Standards: tsconfig, no Stryker, Node floor, lossless loader — PASS

- **tsconfig.base.json** has all R1.1 flags: `strict`, `exactOptionalPropertyTypes`,
  `noUncheckedIndexedAccess`, `module: NodeNext`, `moduleResolution: NodeNext`,
  `target: ES2022`, `verbatimModuleSyntax`, `isolatedModules`, `declaration`.
  All five workspace tsconfigs `extends` the base with no strictness overrides
  (runner/differential only add `"types": ["node"]`). Every package.json has
  `"type": "module"` (ESM).
- **No StrykerJS**: case-insensitive grep across all json/ts/js/yml/mjs (excluding
  node_modules) → zero hits; `ls node_modules | grep -i stryker` → zero. [SA1]
  respected.
- **Node floor**: root `"engines": {"node": ">=20"}`; CI `node-version: 20`;
  audit ran on v24.18.0.
- **Lossless-number loader is real**: `conformance-runner/src/lossless-json.ts`
  is a recursive-descent RFC 8259 parser producing `JsonNumber` wrappers that
  keep the raw token (`18.0` ≠ `18`, >2^53 ints preserved); `loader.ts` routes
  the manifest, every `$bundle` header, and **every vector line** through
  `parseLossless` (loader.ts:217/360/396). `JSON.parse` appears only for
  (i) `corpus.config.json` / selftest-path config (non-vector), and (ii) decoding
  an already-validated string-escape token inside the tokenizer
  (lossless-json.ts:233) — both legitimate. See finding F3 for the wirestub
  test double's `response.json()`.

## (e) Commit hygiene — PASS (minor order deviation, F2)

- `git remote -v` → empty (0 lines). Local-only per D11/D16.
- 14 local commits on `main`. Mapping to D16's 8-item TS granularity plan:
  1→`8fcb9d2` scaffold; 2→`95831bf` compat; 3→`1ef5939` canonicalizer+selftest;
  4→`c6d0167` (corpus snapshot) + `4cc37b3` (loader/codecs/api-map);
  5→`5f41507` VectorFetch/runner/reporting; 6→`8110cea` oracle-ts;
  7→`09171a1` (vendored contracts) + `fe24c41` (ajv referee) + `2702ea6`
  (generated bookmark.ts); 8→`f74da07` GATE.md record. Extra, each well-scoped:
  `80d66a2` (gate enablement: compat/wirestub bindings, authored-apis supplement,
  rawInput seam), `cc41ba9` (corpus re-snapshot @ rig e73f303), `e4dff6e`
  (generated non-printable table). Splits comply with D16's "generated/vendored
  content committed separately" rule.
- api-map provenance chain intact: `api-map.gen.ts` sha256 stamp
  `5bd1db2d…` matches `conformance-runner/corpus/typescript-port-api-map.json`,
  and `context/typescript-port-api-map.json` IS tracked on the Python rig branch
  (D16 Python item 1 satisfied — the design's "currently untracked" concern was
  resolved).
- `git status --porcelain` empty in the TS repo after all audit probes.

## Findings

**F1 (minor, staleness)** — The committed TS corpus snapshot (taken at rig
`e73f303`) predates rig commit `c0eefab`, so the 6 authored
`funnels/live-query-transforms` + `retention/live-query-transforms` vectors never
run in the TS runner (2603 vs the Python rig's 2609). GATE.md discloses this
honestly, and the gate itself only needs compat vectors — but the snapshot should
be re-synced (`scripts/sync-corpus.sh` + commit) before the first Phase-3 batch so
TS conformance counts match the Python corpus.

**F2 (minor, process)** — TS commit sequence deviates from D16's numbered order:
oracle-ts (planned commit 6) landed LAST (`8110cea`), after the referee commits
and the gate-run record (planned commit 8, `f74da07`), and three unplanned
commits exist (`80d66a2`, `cc41ba9`, `e4dff6e`). Granularity and reviewability
are preserved; no content violation. Informational for the orchestrator's ledger.

**F3 (minor, latent pattern)** — `conformance-runner/src/wirestub.ts:198` parses
JSON response bodies with bare `response.json()` (lossy numbers). Harmless here:
it is the D13 test double, the 8 gate vectors avoid float/int-distinguishing
bodies, and all pass. But a real wire-module port copying this pattern would
defeat the lossless-number contract (D6 rule 3) on the OUTPUT side; Phase-3 wire
ports must parse bodies via the lossless path (or the runner must canonicalize
through raw text) — worth a line in the Phase-3 batch instructions.

## Audit hygiene

- No tracked file in either repo was left modified; both sabotage probes were
  reverted via `git checkout` with empty `git status --porcelain` verified after
  each, plus green post-revert reruns (12/12 zfill, 42/42 compat).
- Only writes: this report and temporary scratch/probe files (deleted).
- Pre-existing (not audit-caused) Python-repo working-tree state observed at
  start: modified `context/typescript-port-rulebook.md` + untracked
  `context/phase1/bug-reports/`, `context/phase1/design/escalation-resolutions.md`,
  `context/phase1/pr6-notes.md` — left untouched; flagged for the orchestrator
  since escalation-resolutions.md is design-of-record yet uncommitted.
