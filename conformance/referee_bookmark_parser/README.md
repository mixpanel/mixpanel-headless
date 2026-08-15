# bookmark_parser round-trip referee (design D15b, task PR-11)

Validates Python-built bookmark payloads against the two oracles living in
the READ-ONLY analytics checkout (`/Users/jaredmcfarland/Developer/analytics`
— never written to, never installed into):

| Oracle | Entry point | Verdict |
|--------|-------------|---------|
| **structural** (draft-04) | `bookmark_parser.validate.assert_valid_schema(params, "common/schema/bookmark.json" \| "funnels/schema/bookmark.json")` | pass / `jsonschema.exceptions.ValidationError` |
| **deep** (voluptuous) | `analytics.bookmark_parser.insights.validate.validate_insights_bookmark_params_schema(params, require_all_keys=False)` | pass / `voluptuous.error.MultipleInvalid` |

Both invocation recipes were proven by the recon transcripts in
`context/phase1/recon/referee-assets.md` (§1, §2A, §2B). No CI job runs
these — referee (b) is manual/nightly on a machine with the analytics
checkout (design D15 CI hooks); the D9 release gate includes one batch run.

## Files

- `harness.py` — the referee. Stdlib-only at import time (oracle imports
  are lazy), so the repo test suite unit-tests its routing without the
  analytics checkout. Wheel pins live in its module docstring.
- `handoff.py` — payload-handoff producer. Re-executes every
  bookmark-capability builder vector LIVE under the replay clock and
  cross-checks the output against the recording (drift aborts), so the
  handoff always carries genuine Python-built payloads.
- `handoff.jsonl` — the committed handoff (generated; regenerate after any
  corpus re-extraction).
- `last-run-structural.json` / `last-run-deep.json` — committed batch
  reports (see results below).

## 1. Produce the payload handoff (repo environment)

```bash
uv run python -m conformance.referee_bookmark_parser.handoff \
    --vectors conformance/vectors \
    --out conformance/referee_bookmark_parser/handoff.jsonl
```

Format (D15b): one `{"id", "bookmark_type", "params"}` object per line;
`bookmark_type ∈ {"insights", "funnels", "common"}`.

## 2. Structural draft-04 oracle (PYTHONPATH recipe 1)

```bash
PYTHONPATH=/Users/jaredmcfarland/Developer/analytics \
  uv run --no-project --with jsonschema==4.26.0 \
  python conformance/referee_bookmark_parser/harness.py \
  --oracle structural \
  --handoff conformance/referee_bookmark_parser/handoff.jsonl \
  --out conformance/referee_bookmark_parser/last-run-structural.json
```

## 3. Deep insights voluptuous oracle (PYTHONPATH recipe 2)

Note the different PYTHONPATH: the parent of the checkout, because the
repo root's `__init__.py` makes the checkout itself the `analytics`
package (recon §2B failure ladder).

```bash
PYTHONPATH=/Users/jaredmcfarland/Developer \
  uv run --no-project --with voluptuous==0.16.0 --with protobuf==7.35.1 \
  --with pandas==3.0.5 --with pytz==2026.3.post1 \
  python conformance/referee_bookmark_parser/harness.py \
  --oracle deep \
  --handoff conformance/referee_bookmark_parser/handoff.jsonl \
  --out conformance/referee_bookmark_parser/last-run-deep.json
```

Add `--selftest` (and drop `--handoff`) to either recipe to replay the
recon positive/negative controls — run it first whenever the environment
changes; it proves the oracle wiring is not vacuously green.

Exit codes mirror D9.3: `0` all ACCEPT / controls pass, `1` any REJECT
(**a reject over corpus payloads is a REAL finding — escalate, never
paper over**), `2` harness crash.

## Pinned wheel versions

Resolved at the first scripted run (2026-08-14) and pinned per D15b
(recon had left them "latest at run time", a listed risk):

- structural: `jsonschema==4.26.0`
- deep: `voluptuous==0.16.0`, `protobuf==7.35.1`, `pandas==3.0.5`,
  `pytz==2026.3.post1`

Each report records the versions the running environment actually
resolved (`resolved_versions`).

## Routing rules

**Feed** — the six bookmark-payload builder APIs (all `kind: "builder"`
vectors across capabilities bookmarks/funnels/retention/flows):

| API | bookmark_type | params |
|-----|---------------|--------|
| `workspace.build_params` | insights | as-is |
| `bookmark_builders.build_time_section` | insights | wrapped `{"sections": {"time": ...}}` |
| `bookmark_builders.build_date_range` | common | wrapped `{"date_range": ...}` (recon §2A probe shape) |
| `workspace.build_funnel_params` | funnels | as-is |
| `workspace.build_retention_params` | common | as-is (no retention draft-04 schema exists) |
| `workspace.build_flow_params` | common | as-is (no flows draft-04 schema exists) |

**Structural schema, by dialect (D15b dialect rule)** —
`funnels/schema/bookmark.json` REQUIRES the legacy flat `steps` array, so
it applies only to legacy-dialect funnel params (`"steps" in params`);
modern sections-dialect funnel payloads fall back to
`common/schema/bookmark.json` (the schema's own allOf-common layer).
Feeding modern payloads to the funnels schema would reject correct
library output — the same dead-weight trap D15a documents for ajv.
Verified empirically: a naive route of all 88 modern-dialect funnel
payloads to the funnels schema rejects every one with `'steps' is a
required property` (triaged: dialect misroute, not a library bug —
`build_funnel_params` deliberately emits the modern dialect the App API
stores today; `bookmark_parser/common/migrations/funnels/` converts
between dialects). The funnels schema stays live via the
`funnels-missing-steps` selftest control.

**Deep oracle** — insights payloads only (funnels/common recorded as
`SKIP_NON_INSIGHTS`). Both show-clause dialects are fed: the voluptuous
`Any(...)` union models the modern multi-metric clause
(`behavior`/`measurement`, `insight_multi_metric_show_clause_validator`)
alongside the legacy flat clause; verified empirically at pin time.

## Caveats (D15b comparison rule)

- Verdicts are per-payload ACCEPT/REJECT, never message equality.
- **Deep ACCEPT is necessary-not-sufficient**: the voluptuous schema is
  enum-loose on `math` via an `Any()`/ALLOW_EXTRA branch (recon §2B
  `bad-math-strict -> PASSED`; replayed as the `bad-math-loose` selftest
  control).
- Draft-04 schemas hardcode only 2 levels of filter-group nesting; deeper
  trees pass unvalidated in both languages — never use deep nesting as a
  discriminating vector (D6 rule 4).

## Batch results — 2026-08-14 (corpus @ source commit 5269674)

**Structural (gate criterion): 314/314 ACCEPT, 0 REJECT — PASS.**
Breakdown: 251 modern-nested, 47 legacy-flat (flows), 16 neutral; all via
`common/schema/bookmark.json` (no legacy-dialect funnel payloads exist in
the corpus, so the funnels schema never fired on corpus payloads — it is
exercised by the selftest control only).

**Deep: 123 ACCEPT, 2 REJECT, 189 SKIP_NON_INSIGHTS** (125 insights
entries validated). **The 2 REJECTs are a REAL, OPEN finding (escalated,
not papered over):**

- `bookmarks/workspace.build_params/test_query_params-testfrequencyfilterinbuildparams-test_frequency_filter_in_filter_section`
- `bookmarks/workspace.build_params/test_query_params-testfrequencyfilterinbuildparams-test_frequency_filter_mixed_with_filter`

Both: `required key not provided @ data['sections']['filter'][N]['filterType']`.
Triage: `build_frequency_filter_entry`
(`src/mixpanel_headless/_internal/bookmark_builders.py:784`) emits
`{"behaviorType": "$frequency", "customProperty": {"behavior": {...}},
"resourceType": "people"}` in `sections.filter[]`. The deep validator
requires `filterType` + `filterOperator` on every filter clause
(`bookmark_parser/insights/validate.py:251`, `required=True`), and
analytics' own insights-API fixtures
(`api/version_2_0/insights/test.py:4111`) shape the native frequency
filter clause differently: top-level `filterType`/`filterOperator`/
`filterValue` with the `$frequency` marker nested under
`behavior.behaviorType` — not the library's `customProperty`-nested form.
Whether the live query API tolerates the library's shape cannot be
decided from builder vectors alone (needs a wire-level probe); until
resolved, the TS port must replicate the library's shape byte-for-byte
(bug-compatibility rule R2.x) and this divergence stays on the escalation
list.

## Caveat — structural ACCEPT is near-vacuous for modern-dialect payloads (gate-verdict R6)

The draft-04 `funnels/schema/bookmark.json` covers ONLY the legacy flat
`steps` dialect, so every modern sections-dialect payload — including all
88 modern-dialect funnel payloads in the corpus — routes to the permissive
`common/schema/bookmark.json` (see "Routing rules" above). That schema
constrains almost nothing about the modern sections shape, so a structural
ACCEPT on a modern-dialect payload carries near-zero discriminating power:
the 314/314 structural PASS should not be read as deep validation of
modern payloads. The routing itself is verified sound (a deliberate
misroute of the 88 modern funnel payloads to the funnels schema rejects
every one), and the insights side is independently covered by the deep
voluptuous oracle and the TS Ajv referee — but the modern FUNNELS payloads
currently have minimal oracle coverage. **Deep-oracle coverage for
modern-dialect funnels (a vendored sections schema or wire-level probes)
is a tracked Phase-2+ gap** (GATE-VERDICT.md finding L5-F2 /
recommendation R6); do not treat structural ACCEPT alone as evidence of
modern-funnels conformance.
