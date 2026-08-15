# Escalation resolutions (user rulings, 2026-08-14)

The four escalations in `phase1-design.md` §Escalations were put to the user and ruled
as follows. These rulings are binding on all subsequent Phase-1+ work. This file is
intentionally separate from `phase1-design.md` (which was committed by rig task PR-1
before these rulings landed); treat the two together as the design of record.

## E1 — analytics storybook mock copying (D3.1): **APPROVED, with scrubbing**

Scrubbed copying of `iron/.storybook/mocks/api/` bodies into the mixpanel-headless
conformance corpus is permitted.

Execution (queued as post-build addendum work, not part of the running build workflow):
harvest the 81 files (~1.2 MB), unwrap the 9 `{body, init}` storybook wrapper files,
re-key internal identifiers (demo project id 3018488, the 5 employee emails, creator
ids) to synthetic values, and emit them as `parse`-kind vectors under
`conformance/vectors/authored/parse/` with `origin: "authored"` and a provenance note
naming the source path. The `"totalCount": "10254"` string-count realism and the
502-wrapper error bodies are the primary payoff (D3.1).

## E2 — uncoded-ValueError coding pass (R5.5): **YES — Python-side coding pass lands BEFORE Phase 2**

The ~130 uncoded builder guard sites (`ValueError`/`TypeError`, incl. the CF1/CF2 /
CB1/CB2 / CM1/CM2 docstring-label families) get real registry codes via a Python `src/`
change, executed after the Phase-1 build + gate audit and before Phase 2 starts.

Sequencing consequences (per R10.7: fix Python first, regenerate vectors, then port):
1. Coding pass as its own TDD workflow on a branch based on `ts-port/phase1-verification-rig`.
2. Re-extract the corpus (the `uncoded_raise` manifest bucket shrinks; new
   `validation-error` vectors appear for those sites); re-run the Python runner, the
   drift check, and the D9 smoke test; TS repo re-syncs its corpus snapshot.
3. The manifest `excluded.uncoded_raises` worklist from PR-5 is the task list.

## E3 — FormulaShowClause `oneOf` ambiguity (D15a): **bug report filed locally**

Report: `context/phase1/bug-reports/analytics-bookmark-schema-formula-showclause-oneof.md`.
Fixture policy stands as designed: every generated show clause sets `"type"` explicitly.
Raising the report with analytics owners is a user action; nothing further blocks on it.

## E4 — alerts contract source (D15c): **Python is the contract source**

Ruling: the alerts contract "maps to whatever Python maps to" — i.e. the endpoints and
shapes `mixpanel_headless`'s alerts CRUD actually uses (locked by the extracted wire
vectors) are authoritative. The vendored schema4api `alerts/custom` `types.d.ts` is
advisory only: during Phase 2 type vendoring, verify Python's alert endpoint paths
against that surface; where they diverge, derive TS types from the Python wire behavior
(vectors + result shapes) and record the divergence in `vendor/mixpanel-contracts/PROVENANCE.json`
rather than trusting the vendored file.
