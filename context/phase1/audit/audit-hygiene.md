# Phase-1 Audit — LENS 6: Process Hygiene

Auditor: independent (re-executed every check; no build-agent claim trusted).
Date: 2026-08-15 (checks run ~00:00-00:05 local).
Repos: Python `/Users/jaredmcfarland/Developer/mixpanel-headless` @ `ts-port/phase1-verification-rig` (63db3b0);
TS `/Users/jaredmcfarland/Developer/mixpanel-headless-ts` @ `main` (8110cea).

**Verdict: PASS with minor findings.** No publishing, no analytics contamination, no ~/.mp
residue, whitelist compliant; all four reported deviations are documented and none silently
contradicts a binding rule. Findings are documentation/residue hygiene only.

---

## (a) No publishing anywhere — PASS

- Python repo remotes: `origin` (mixpanel/mixpanel-headless) + `gslopez` (pre-existing fork remote).
- `ts-port/phase1-verification-rig` has **no upstream** (`git for-each-ref` shows empty upstream);
  `git log origin/fix/latent-bugs-stress-test..ts-port/phase1-verification-rig` = **17 commits,
  local-only** (4f885f4 … 63db3b0).
- `git ls-remote origin 'refs/heads/ts-port/*' 'refs/heads/*phase1*' 'refs/heads/*conformance*'`
  → **empty**.
- Cross-check for any new remote branch under any name:
  `comm -13 <(local origin/* tracking refs) <(git ls-remote --heads origin)` → **empty**
  (no remote head exists that local tracking refs don't already know).
- `gh pr list --state all --head ts-port/phase1-verification-rig` → **empty**.
- TS repo: `git remote -v` → **zero remotes**; single branch `main`; clean worktree. Nothing
  can have been pushed from it.
- **PR #206 note (not a violation)**: `gh pr view 206` → author `jaredmixpanel`, head
  `fix/latent-bugs-stress-test`, created 2026-08-14T23:47:30Z; remote-ref reflog shows one
  push of that branch at 2026-08-14 16:47:16 -0700 landing **exactly 5269674** (the pinned
  rig base — zero rig content). This is explicitly sanctioned by the design of record:
  phase1-design.md D16 (line 434) — "PR #206 is intentionally unmerged; the orchestrator
  owns merge sequencing."

## (b) analytics checkout untouched — PASS

- `git -C …/analytics status --porcelain` → **empty** (tracked and untracked both clean).
- `git stash list` → empty; branch `master` @ c2bcbe895e7 (upstream commit, MULTI-839).
- No mtime inspection needed given a fully clean porcelain.

## (c) ~/.mp hygiene — PASS

- `~/.mp/accounts/` contains only `mixpanel` and `mixpanel-2`. Both are **pre-existing real
  accounts**: `me.json` dated Aug 4 (10:40 / 11:12), `config.toml` dated Aug 4, both
  `type = "oauth_browser"`; `tokens.json` mtimes Aug 14 15:42/15:44 are routine token
  refreshes (before the rig-build's main activity window).
- `facade` / `test_account` confirmed **deleted**: `find ~/.mp -iname '*facade*' -o -iname
  '*test*'` → no matches. The `accounts/` dir mtime (Aug 14 22:02) is consistent with their
  creation+deletion during the PR-6 re-extraction window (re-extract-pr6 logs 22:01-22:05).
- Nothing test-created remains.

## (d) Whitelist compliance — PASS (one mechanical addendum noted)

Files changed outside `conformance/` + `context/` on `5269674..ts-port/phase1-verification-rig`:
`.github/workflows/ci.yml`, `justfile`, `pyproject.toml`, `uv.lock`. Nothing else
(`git diff --name-status` with pathspec excludes — verified).

- **pyproject.toml** (3 added lines, dev extras only): `freezegun>=1.5`, `jsonschema>=4.21`
  (both explicitly permitted, D17.7) + `types-jsonschema>=4.21` (documented deviation — see (f)1).
  No other section touched; runtime deps untouched (D17.6/7 honored).
- **justfile**: every hunk maps to D17/D8 — `check` gains `conformance` (D8); `typecheck`
  gains `conformance/` (D17.1); `docstring-cov` gains `interrogate conformance/
  --fail-under=95` (D17.3, additive third line); new recipes `conformance`,
  `conformance-record`, `conformance-smoke` (D18/PR-1, D9). All additive; existing recipes
  otherwise untouched.
- **.github/workflows/ci.yml**: matches the D8 job shape — sibling `conformance` job,
  ubuntu-latest, Python 3.12 only; same pinned action SHAs as the existing `test` job
  (checkout v6.0.2, setup-python v6.2.0, setup-uv v8.1.0) and mirrored
  `permissions: contents: read`; steps = sync / `mypy conformance/` / `pytest
  conformance/tests` / `pytest conformance/runner` / drift check with manifest-injected
  `--mp-record-date`/`--mp-record-commit` and `HYPOTHESIS_PROFILE: ci`; `conformance/**`
  added to **both** `paths:` lists. One deviation from the spec's literal command text
  (`uv run python -m pytest` in the drift step) — documented inline and in
  conformance/record/README.md (see (f)2).
- **uv.lock**: not named in D17, but the diff is purely mechanical fallout of the three dev
  deps — additions only (`freezegun`, `jsonschema`, `types-jsonschema` + transitives
  `jsonschema-specifications`, `referencing`, `rpds-py`), **zero removals, zero version
  bumps of existing packages**. Judged compliant; noted as finding H3 because the letter of
  the whitelist doesn't mention it.

## (e) Worktree / tmp residue — PASS with cleanup list

- `git worktree list` (Python repo): main tree + `/Users/jaredmcfarland/Developer/
  mixpanel-headless-pr195` [pr195-fixes] — **pre-existing** (created 2026-07-06, tracks the
  gslopez fork branch; unrelated to the rig). No `/tmp/mp-smoke-*` worktree registrations
  remain (smoke worktrees were pruned properly). TS repo: single tree.
- `/tmp/mp-smoke-*` and stale rig scratch: no `mp-smoke` dirs remain, but the following
  **rig residue is flagged for cleanup** (all Aug 14, harmless, /tmp writes were in-mandate
  for builders): dirs `pr2/`, `pr3-pilot/`, `pr3-pilot2/`, `pr5/`, `re-extract-pr6/`,
  `re-extract-pr6b/`, `referee-probe/`, `probe-u24/`, `ts7-repros/`, `apimap/`,
  `__pycache__/`; files `author_pr7.py`, `pr10-self-parity.json`, `pr9-drift-pytest.log`,
  `pr9-justcheck.log`, `justcheck.log`, `smoke-full.log`, `smoke-full2.log`,
  `re-extract-pr6*.log`, `final-report.json`, `ts8-entries.json`, `ts7-repros`,
  `tsconfig.bak`, `tsconfig-gen.json`, assorted `*.txt`/`*.json` scratch
  (`seg_headers.txt`, `wire_files.txt`, `wirefiles.txt`, `inv.json`, `bm_body.json`,
  `codes_schema.txt`, `code_testfiles.txt`).
  (`/tmp/audit/` is a concurrent auditor's scratch — mtimes 23:58-23:59, not build residue.)

## (f) Reported deviations — all documented, none silent

1. **types-jsonschema dev dep** — documented in commit 4f885f4's message: "jsonschema ships
   no py.typed; stubs required for the D17.1 mypy --strict bar — mirrors the existing
   psutil/types-psutil pairing; documented deviation from the two-package wording."
   Dev-only; serves the binding D17.1 strict-typing rule. Not silent, not contradictory.
2. **`uv run python -m pytest` in CI drift step** — deviates from D8's literal
   `uv run pytest` command text; required so repo root lands on sys.path for
   `-p conformance.record.plugin`. Documented three places: ci.yml inline comment,
   justfile `conformance-record` comment ("found at PR-5 first invocation"),
   conformance/record/README.md (lines 11, 22). Not silent.
3. **KeepOrderDict vs D3 sorted-keys** — commit 4eb0b9f documents it fully: call.input /
   setup input / response-body subtrees serialize in insertion order because "sorted-keys
   storage was lossy for order-sensitive payloads (form bodies, json.dumps'd strings,
   dict-key-iteration results); comparisons stay canonical-sorted; still byte-deterministic."
   D3's operative goal (byte-identical re-extraction) is preserved and mechanically enforced
   by the CI drift byte-diff; the comparison canonicalizer still sorts, so no comparison
   semantics changed. The TS-loader order-preservation obligation is recorded in
   context/phase1/pr6-notes.md (L42, L50). Not silent — but see findings H1/H2: pr6-notes.md
   is untracked and phase1-design.md's D3 text (line 114) was never amended, so the design
   letter is now stale.
4. **Schema copy divergence** (conformance/schema/vector.schema.json vs
   context/phase1/design/vector.schema.json) — 4 purely additive extensions in the
   conformance copy, each carrying a `$comment` with provenance: `client_options.max_retries`
   ("Extension (12), PR-5 audit finding F4"), `session.headers` (PR-6),
   `transportError.message` (PR-6, with the R5.4 cross-language caveat), plus the enclosing
   object plumbing. The design-dir copy is the frozen PR-1 snapshot; the conformance copy is
   the operative validator. Self-documenting; consistent with the PR-6 gate rule ("fix the
   pipeline, never hand-edit vectors"). Minor staleness risk noted (H5).

---

## Findings (all minor)

| # | Finding | Detail / recommendation |
|---|---------|-------------------------|
| H1 | Deviation/design docs untracked | `context/phase1/design/escalation-resolutions.md` (part of the design of record), `context/phase1/pr6-notes.md` (KeepOrderDict + schema-addition deviation trail), `context/phase1/bug-reports/` exist only as untracked working-tree files — not SHA-pinned, at risk of loss. Commit them on the rig branch. |
| H2 | phase1-design.md D3 letter stale | D3 line 114 still says "sorted keys" unconditionally; implemented behavior (KeepOrderDict subtrees) is documented only in commit 4eb0b9f + untracked pr6-notes.md. Add an amendment note to D3 or escalation-resolutions.md. |
| H3 | uv.lock outside the literal whitelist | Mechanical, additions-only fallout of the D17.7 dev deps (verified: no removals, no existing-package bumps). No action beyond acknowledging in the whitelist wording. |
| H4 | Uncommitted edit to tracked `context/typescript-port-rulebook.md` | Working-tree-only addition of rule R10.13 `[ST2]` (orchestrator process-hygiene amendment re xhigh agents). Legitimate content, but currently unpinned — commit it. |
| H5 | Design-dir vector.schema.json stale vs operative copy | 4 additive divergences (self-documented via `$comment`s). Either declare conformance/schema the single source of truth in the design doc or back-port. |
| H6 | /tmp residue | Cleanup list in section (e). Harmless; in-mandate writes. |

No blocker or major findings. Nothing was published; the analytics checkout and ~/.mp are
clean; every out-of-scope file change maps to a permitted or documented edit.
