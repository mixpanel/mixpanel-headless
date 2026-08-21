# context/

## TypeScript-port docs have moved

The TypeScript port's spec of record — the master plan, rulebook, api-map, and
all per-phase design docs, task packets, review resolutions, notes, gate
reports, and the Phase-4 inbound ledger — now lives **in the TS repo**:

> `github.com/jaredmixpanel/mixpanel-headless-ts` under `context/`
> (local checkout expected at `../mixpanel-headless-ts`)

The docs were relocated at the close of Phase 3 (2026-08-17), mirrored verbatim
from this repo at branch `ts-port/python-bugfix-batch` @ `80dc0a3`; their full
history remains in this repo's git log. Citations elsewhere in this repo (source
docstrings, `conformance/differential/oracle/RUN.md`, commit messages) that name
`context/phase*/...` paths resolve against that mirror.

## What stays here

- **`conformance/`** (repo root, not this directory) — the conformance corpus,
  record-mode extraction plugin, runners, differential oracle, and referees.
  These are coupled to the Python test suite and re-pin choreography, and are
  the artifacts the TS repo snapshots via its `npm run sync:corpus`.
- **Python bug reports** for bugs found by the port (all four fixed by the
  R10.7 batch on this branch):
  - `phase1/bug-reports/mixpanel-headless-frequency-filter-clause-shape.md`
    (+ the live probe record `phase1/addendum/frequency-filter-probe.md`)
  - `phase3/bug-reports/mixpanel-headless-datagroupid-int-clause.md`
  - `phase3/bug-reports/python-handle-response-403-typeerror.md`
  - `phase3/bug-reports/python-oauth-error-details-token-payload.md`
  - `phase1/bug-reports/analytics-bookmark-schema-formula-showclause-oneof.md`
    (upstream analytics schema issue, informational)
- **Pre-existing design docs** unrelated to the port:
  `frictionless-auth.md`, `session-replay-plan.md`.
