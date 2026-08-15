# Frequency-filter live probe (GATE-VERDICT R7 — task AD-8)

**Question** (escalation from the deep-oracle referee, `conformance/referee_bookmark_parser/README.md`
and `context/phase1/audit/audit-oracles-referees.md` §(d)): does the live Mixpanel query engine
accept the library's frequency-filter clause shape — `build_frequency_filter_entry`'s
`customProperty`-nested form in `sections.filter[]` — or reject it?

**VERDICT: REJECTS (server HTTP 5xx on the library's shape) — real Python-library bug, filed per
R10.7 as `context/phase1/bug-reports/mixpanel-headless-frequency-filter-clause-shape.md`. NOT
fixed in this workflow.**

## Probe setup

- Date: 2026-08-15. Account `mixpanel-2` (oauth_browser, us), project 3.
- Credentials verified first: `uv run mp account test mixpanel-2` → `"ok": true`
  (user jared@mixpanel.com, 90 accessible projects).
- Budget discipline: exactly **3 Query-API calls**, all read-only; no entities created.

## The three calls

1. **`/api/query/events/top`** (via `ws.top_events(limit=10)`) — pick a high-volume probe event.
   Chose `Query` (1,179,203 events that day).
2. **Baseline** — `ws.query("Query", last=7, math="total", mode="total")` → **HTTP success**:
   `{"[Verified] Query Executed [Total Events]": {"all": 77705787}}`.
3. **Frequency-filtered** — identical query plus
   `where=FrequencyFilter("Query", value=500000)` → **`mixpanel_headless.exceptions.ServerError:
   Server error: An unknown error occurred.`** (HTTP 5xx; Mixpanel's opaque 500 body).

The exact clause on the wire for call 3 (recorded locally via `ws.build_params(...)` before the
call — byte-identical to the two escalated handoff payloads' shape):

```json
[
  {
    "behaviorType": "$frequency",
    "customProperty": {
      "behavior": {
        "aggregation": "total",
        "event": "Query",
        "filterOperator": "is at least",
        "filterValue": 500000
      }
    },
    "resourceType": "people"
  }
]
```

## Interpretation

- The audit's static reading (§(d)) established that the voluptuous validation gate is in
  **dry-run** at the query call site: a `required key not provided @ …filter[N][filterType]`
  error is logged and the query **proceeds to execute**. The probe result is exactly consistent:
  the request was not 4xx-rejected by validation — it reached the engine and the engine failed
  with an unhandled 500.
- The baseline call with the same event/range/math succeeded seconds earlier over the same
  connection; the only delta in call 3 is the frequency-filter clause. The engine cannot
  process the `customProperty`-nested form (the platform-native clause is top-level
  `filterType`/`filterOperator`/`filterValue` with `$frequency` under `behavior.behaviorType` —
  analytics `api/version_2_0/insights/test.py:4111`).
- So the earlier "server tolerates the shape today" hypothesis (audit §(d) verdict (ii)) holds
  only at the VALIDATION gate; at the EXECUTION layer the shape fails. The deep validator is
  NOT stale — it flags a clause the engine genuinely cannot run.

## Caveats

- **n = 1** on the failing call. `ServerError` (5xx) can in principle be transient; the probe
  budget (≤3 Query-API calls, shared 60/hr) was exhausted, so no confirmation retry was made.
  The timing correlation (baseline success immediately prior), the opaque-500 signature, and the
  independent static evidence (validator required keys + platform-native fixture shape both
  disagree with the library's shape) together make "transient blip" the strained reading, but a
  single confirmation retry in a later budget window would make this airtight. Recommended:
  re-run call 3 once (1 Query-API call) before acting on the Python-side fix.
- The probe settles ACCEPT/REJECT. The subtler "interpreted vs silently ignored" branch never
  arises: the engine neither ignores nor interprets the clause — it crashes.

## Disposition

- **Escalation: settled as REJECTS, remains tracked as an OPEN Python bug** (R10.7 protocol):
  fix belongs in `build_frequency_filter_entry`
  (`src/mixpanel_headless/_internal/bookmark_builders.py:784`) — NOT performed in this
  sanctioned workflow (out of the coding-pass mandate; needs its own TDD + vector regeneration).
- **TS port: keep replicating the Python shape byte-for-byte** (R2.x) until the Python fix
  lands and vectors are re-extracted from the fixed behavior; then port the fix (R10.7 order:
  Python first, regenerate vectors, then TS).
- The two deep-oracle REJECTs in `last-run-deep.json` stay expected-and-disclosed (exit 1 by
  design) until that fix + re-extraction cycle.
