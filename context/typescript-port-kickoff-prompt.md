# Kickoff prompt for the TS-port pipeline session

Paste the block below into a fresh Claude Code session in this repo. Optionally append a
token-budget directive (e.g. `+2m`) to the first line to scale workflow depth.

---

ultracode: use a workflow

Begin executing the TypeScript port of mixpanel-headless — Phase 1 onward of
`context/typescript-port-plan.md` — using dynamic workflows for every substantive phase.

**Read first, in this order:**
1. `context/typescript-port-plan.md` — architecture, the 5-layer verification stack, phase
   plan, exit criteria (Phase 0 is complete; you are starting Phase 1).
2. `context/typescript-port-rulebook.md` — v1.1. AUTHORITATIVE for every translation
   decision. Rules R10.1–R10.12 govern your own workflow behavior, not just the code.
3. `context/typescript-port-api-map.json` — the mechanical queue (205 Workspace members,
   batches B0–B9). The .md twin is the human view.

**Ground state (do not re-derive):**
- Work from branch `fix/latent-bugs-stress-test` (PR #206, intentionally unmerged — do NOT
  merge it). Base any new Python-repo branches on it, and stamp every extracted vector
  file with the source commit SHA so the corpus can be regenerated after #206 merges.
- The TS repo does not exist yet. Create it locally at
  `/Users/jaredmcfarland/Developer/mixpanel-headless-ts` per plan §4.1 (git init only —
  do not create or push a GitHub repo without asking).
- `/Users/jaredmcfarland/Developer/analytics` is read-only reference: bookmark JSON
  Schema (`lib/common/mxpnl/report/bookmarks/generated/bookmark.json`), `bookmark_parser/`,
  schema4api `types.d.ts`, iron idioms (`iron/common/report/queries/`). Never write there.
- Live credentials exist (`mp account test mixpanel-2` refreshes tokens); Query API budget
  is 60 q/hr — spend it only on referee/live checks, never in loops.

**Execution contract:**
- One workflow per phase (or per batch within Phase 3); read each workflow's results
  before launching the next. Adversarial verification for anything load-bearing, per plan
  §5 and rulebook R10.9 (throwaway differential harness with the mandatory edge-case set
  before review — integral float, fractional float, True, None, empty list, empty string,
  non-BMP string, every error branch).
- Phase 1's gate is mechanical — self-verify and continue without asking: (a) Python
  passes 100% of its own extracted corpus in CI-runnable form, (b) the corpus kills
  mutmut mutants at parity with the original suite for covered modules, (c) the TS
  scaffold's conformance runner goes green on a hello-world module.
- Stop and ask ONLY when: a rulebook ambiguity needs a human call (R10.3 escalation), a
  phase gate fails twice after pipeline-level fixes, or an action requires
  merge/push/publish. Everything else: proceed.
- R10.4 applies to the pipeline itself: any failure pattern recurring ≥3 times amends the
  rulebook and regenerates affected artifacts. Log every amendment with an `[ST2]` tag.
- Model tiering per plan Phase 3: high-volume translation on a cheaper tier; the
  extractor, api_client, auth subsystem, and all review/arbitration on the strongest.
- Vector schema: plan Appendix A. Canonicalization rules as specified there, plus
  rulebook R10.11 (numeric-string normalization ONLY in number-filter operand positions)
  and R5.4 (strip error messages; compare class name + code).
- End every phase with a written status the user can read cold: what shipped, gate
  results with numbers, rulebook amendments, cost notes, and what the next workflow does.

**Scope guardrails:** CLI deferred; no pandas; no Zod (R4.2); browser tier per plan §4.3
(browser-origin PKCE verification deferred to batch B9); `core` package imports nothing
from `node:*` (R9.1). Do not modify permission settings, CLAUDE.md, or anything in
`../analytics`.

**Start now with Phase 1 — the verification rig**, in dependency order: record-mode
pytest plugin → `conformance/` corpus (extracted, SHA-stamped) → Python corpus runner →
judge validation via mutmut → TS repo scaffold (strict tsconfig per R1.1, Vitest,
fast-check, StrykerJS) → TS conformance runner → differential bridges (`oracle-py`,
`oracle-ts`) → referee harnesses (bookmark.json validation, `bookmark_parser` round-trip,
schema4api type regeneration).
