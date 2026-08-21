# Bug report: `build_frequency_filter_entry` emits a filter-clause shape the live query engine cannot execute (HTTP 500)

**Repo**: `mixpanel-headless` (this repo)
**Artifact**: `src/mixpanel_headless/_internal/bookmark_builders.py` — `build_frequency_filter_entry`
(def at line 805; reachable via `Workspace.query(..., where=FrequencyFilter(...))` and
`Workspace.build_params(..., where=FrequencyFilter(...))`)
**Filed by**: TypeScript-port verification work (Phase 1 addendum, task AD-8), 2026-08-15.
Escalated by the deep-oracle referee (2 REJECTs in
`conformance/referee_bookmark_parser/last-run-deep.json`), triaged statically in
`context/phase1/audit/audit-oracles-referees.md` §(d), settled by the GATE-VERDICT R7 live probe
(`context/phase1/addendum/frequency-filter-probe.md`).
**Status**: OPEN — R10.7: reported, NOT fixed in the Phase-1 addendum workflow. Fix requires its
own TDD cycle + full conformance-vector re-extraction (the corpus records the current shape).

## Symptom

`ws.query("Query", last=7, math="total", mode="total", where=FrequencyFilter("Query", value=500000))`
against live project 3 (us) fails with
`mixpanel_headless.exceptions.ServerError: Server error: An unknown error occurred.` (HTTP 5xx),
while the identical query without the frequency filter succeeds seconds earlier
(returned 77,705,787 total events). n = 1 live observation (probe budget); see the probe record
for the confirmation-retry recommendation.

## Root cause

The library emits, in `sections.filter[]`:

```json
{"behaviorType": "$frequency",
 "customProperty": {"behavior": {"aggregation": "total", "event": "Query",
                                 "filterOperator": "is at least", "filterValue": 500000}},
 "resourceType": "people"}
```

The platform-native frequency filter clause (analytics `api/version_2_0/insights/test.py:4111`,
and the required keys in `analytics/bookmark_parser/insights/validate.py` ~251) is shaped with
**top-level** `filterType` / `filterOperator` / `filterValue` and the `$frequency` marker nested
under `behavior.behaviorType` — not the library's `customProperty`-nested form. Server-side
required-key validation over filter clauses is currently in dry-run (logged, not enforced —
try/except with "TODO remove" at `analytics/api/version_2_0/insights/params.py:2946-2972`), so
the malformed clause passes the gate and the query engine then fails with an unhandled 500.

## Impact

- Every live insights query or saved bookmark using `FrequencyFilter` in `where=` is broken
  (query path 500s; the bookmark save path shares the same dry-run gate, so saved reports would
  carry a clause the engine cannot run).
- When Mixpanel finishes the validation rollout (removes the try/except), the shape will start
  failing loudly at BOTH the query and the bookmark save gates.
- Conformance: the 2 deep-oracle REJECTs
  (`…test_frequency_filter_in_filter_section` / `…test_frequency_filter_mixed_with_filter`)
  are true positives — the deep validator is NOT stale.

## Suggested fix (Python first, per R10.7)

Reshape `build_frequency_filter_entry` output to the platform-native clause (top-level
`filterType`/`filterOperator`/`filterValue`, `$frequency` under `behavior.behaviorType`),
mirroring the analytics fixture; add a live smoke against the query API; then regenerate the
conformance corpus and port the fixed behavior to TS. Until then the TS port must replicate the
current (broken) shape byte-for-byte (R2.x bug-compatibility — oracle divergence otherwise).
