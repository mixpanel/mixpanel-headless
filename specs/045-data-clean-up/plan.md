# Implementation Plan: `data-clean-up` — a Mixpanel governance skill

**Branch**: `045-data-clean-up` (proposed) | **Date**: 2026-06-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/045-data-clean-up/spec.md`
**PR strategy**: Single PR. The feature is a Claude Code skill (Markdown assets + one tested helper script). It has no phased library rollout — the `Workspace` governance surface it calls already shipped (042/189/190). The PR adds `mixpanel-plugin/skills/data-clean-up/` plus tests for the one bundled script.

## Summary

Add a governance / data-dictionary skill, `data-clean-up`, that curates a Mixpanel project's Lexicon so it reads like a human tracking plan rather than an SDK firehose. The skill is the "Invisible Woman" persona expressed as a Claude Code skill: it grounds in business context + `schema_graph(include_density=True)`, classifies every event and property with explicit KEEP/HIDE taste, auto-derives display names + domain-grounded descriptions + sampled example values, batches the un-inferable tail into one question, ships every write behind a single approval gate, executes via bulk Lexicon updates, verifies by re-fetch + diff, and emits a re-runnable drift-check artifact the user owns.

The work is overwhelmingly **prose and judgment** (a `SKILL.md` plus three `references/` documents that capture the keep/hide taste, the naming/annotation rules, and the drift-check contract) plus exactly ONE piece of new shipped Python: `governance_check_template.py`, a standalone drift-checker the skill stamps out for the user. That template is the only code under the repo's strict gates; it gets full TDD treatment. The skill calls the already-public `Workspace` governance methods and adds NO new `src/` code.

Estimated scope: ~1 `SKILL.md` + 3 reference docs + 1 bundled script (~250 LoC) + its tests (~300 LoC) + fixtures. One PR, ~1 week of focused work, most of it taste capture and trigger tuning.

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict compliant) for the one bundled script; Markdown for the skill assets.

**Primary Dependencies**:
- Reused at skill runtime: `mixpanel_headless` (the `Workspace` governance surface), `pandas` (the skill reads `schema_graph` DataFrames), the plugin's `help.py` and hosted docs for API discovery.
- The bundled `governance_check_template.py` depends only on `mixpanel_headless` + stdlib (env-first creds, JSON spec on disk). It carries an inline `pip install mixpanel_headless` header so a user can run it standalone outside this repo.

**Storage**: None in the library. The skill writes user-owned artifacts to a user-chosen output directory: `governance_plan.md`, `governance_apply.py`, `governance_spec.json`, `governance_check.py`. None of these are committed; only `governance_check_template.py` (the stamp source) lives in the repo.

**Testing**: pytest for `governance_check_template.py` — unit tests of its drift-detection logic against fixture (spec, live-schema) pairs covering each drift class (new un-annotated event, dropped governed entity, rename, coverage shift, re-appeared noise) and the clean no-drift case. No live API in the unit suite; the schema is a fixture dict. The Markdown assets are reviewed for taste fidelity and trigger accuracy (a skill-trigger eval), not unit-tested.

**Target Platform**: Cross-platform. The skill runs wherever Claude Code + `mixpanel_headless` run. The drift-checker runs wherever Python 3.10+ + `mixpanel_headless` run (developer laptop, cron box, CI runner).

**Project Type**: Claude Code plugin skill addition. No `src/` change. Mirrors the existing `mixpanelyst` / `dashboard-expert` skill packaging.

**Performance Goals**:
- Grounding (`get_business_context_chain` + `schema_graph(include_density=True)`) ≤ 2 round trips for any project.
- `property_values` sampling bounded to KEEP-candidate properties only (not every property), to respect rate limits.
- Main execution issues O(1) bulk calls per entity kind (`bulk_update_event_definitions`, `bulk_update_property_definitions`), not O(N) single PATCHes.
- The drift-checker is a single `schema_graph` fetch + an in-memory diff; sub-second after the fetch.

**Constraints**:
- mypy --strict, ruff format / check, ≥90% coverage, complete docstrings on `governance_check_template.py` and its tests (the only shipped code).
- The skill MUST NOT add `src/` code, MUST NOT bundle a copy of `help.py`, MUST defer API discovery to `help.py` + hosted docs.
- The skill MUST NOT auto-delete / auto-drop / auto-merge, and MUST gate PII `sensitive`/hide behind a separate confirmation.
- Every shared-state write goes behind the single approval gate; irreversible ops get extra-explicit confirmation.

**Scale/Scope**:
- 1 `SKILL.md`, 3 reference docs, 1 bundled script (~250 LoC), ~300 LoC of tests, ~3 fixture files. One PR.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Library-First | PASS | The skill delegates 100% of writes to existing public `Workspace` methods (`bulk_update_event_definitions`, `update_property_definition`, `create_lexicon_tag`, `set_business_context`, …). It adds no `src/` code. The one bundled script uses only the public surface. |
| II. Agent-Native | PASS | All grounding and classification is structured (schema_graph DataFrames, property_values lists). The only interactive points are the single approval gate and the ONE batched question list — deliberate, not chatty. The drift-checker is non-interactive (exit code + report) and pipe/cron-composable. |
| III. Context Window Efficiency | PASS | `SKILL.md` is terse + table-driven; depth lives in `references/` (progressive disclosure). The skill batches the un-inferable tail into ONE question rather than dripping prompts. Bulk writes keep the API transcript compact. |
| IV. Two Data Paths | PASS | Live path: `schema_graph` / `property_values` / `get_business_context_chain`. Local path: the governance plan + `governance_spec.json` are local artifacts the user diffs offline; `governance_check.py` re-reads the spec locally and re-fetches live for the diff. |
| V. Explicit Over Implicit | PASS | KEEP/HIDE each carry a stated reason; the un-inferable tail is surfaced, never guessed; the approval gate is explicit; PII and merge get extra-explicit confirmation; idempotent re-runs say "nothing to do" rather than silently re-writing. |
| VI. Unix Philosophy | PASS | `governance_check.py` exits non-zero on drift → drops into cron/CI. `governance_spec.json` is a plain JSON artifact other tools can read. The skill emits artifacts the user owns rather than hiding state. |
| VII. Secure by Default | PASS | No PII is ever auto-actioned; `sensitive`/hide require a separate confirmation; nothing is ever auto-deleted/dropped/merged. The bundled script uses env-first credentials (`MP_USERNAME` / `MP_SECRET` / `MP_PROJECT_ID` / `MP_REGION` per CLAUDE.md, no secrets in source). |

**Gate Result**: PASS. No violations. The skill is additive prose + one tested script over an already-approved governance API.

## Project Structure

### Documentation (this feature)

```text
specs/045-data-clean-up/
├── plan.md                       # This file
├── spec.md                       # Feature specification
├── research.md                   # Phase 0 — decisions + the keep/hide taste rules with worked examples
├── quickstart.md                 # End-to-end walkthrough of a cleanup + drift-check
└── tasks.md                      # Phase 2 output (via /speckit-tasks)
```

### Source / asset layout (repository root)

```text
mixpanel-plugin/
└── skills/
    └── data-clean-up/                          # NEW SKILL
        ├── SKILL.md                            # NEW — terse, table-driven; the trigger description; the 8-step flow
        ├── references/
        │   ├── governance-taste.md             # NEW — keep/hide taste with worked examples (browser vs browser_version,
        │   │                                   #        utm_source sparse-but-keep, granularity discrimination, <50/<100 target)
        │   ├── display-name-and-annotation-rules.md  # NEW — snake/camel/ALL_CAPS → Title Case; ios_ → "(iOS)";
        │   │                                   #        feature grouping with ":"; description grounding; example_value sourcing;
        │   │                                   #        tag vocabulary (no emoji); verified/sensitive semantics
        │   └── drift-check.md                   # NEW — governance_spec.json shape; drift classes; exit-code contract;
        │                                       #        how the skill stamps governance_check.py from the template
        └── scripts/
            └── governance_check_template.py     # NEW (ONLY shipped code) — standalone drift checker; pip header;
                                                 # env-first creds; schema_graph diff vs spec; non-zero exit on drift

tests/
└── unit/
    └── plugin/
        └── test_governance_check_template.py    # NEW — drift-detection logic against fixture (spec, live) pairs

tests/fixtures/
└── governance/
    ├── governance_spec_sample.json              # NEW — a governed-schema snapshot fixture
    ├── live_schema_clean.json                   # NEW — live schema matching the spec (no drift)
    └── live_schema_drifted.json                 # NEW — live schema with each drift class injected
```

**Structure Decision**: Plugin-skill layout matching the existing `skills/mixpanelyst/` and `skills/dashboard-expert/` packages. The only code under the repo's strict gates is `scripts/governance_check_template.py`; everything else is reviewed Markdown. Tests for the bundled script live under `tests/unit/plugin/` to keep plugin-script tests separate from the library suite while still running under the same `just check`.

> **Note on test location**: if the project does not yet have a `tests/unit/plugin/` directory or a coverage path that includes `mixpanel-plugin/`, the Setup phase establishes it (and wires the template into the coverage config) before any test is written. The bundled script must be importable by the test (e.g. via a path insert or a `conftest.py` shim) so `mypy --strict` and coverage both see it.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Decision | Why Needed | Simpler Alternative Rejected Because |
|----------|------------|-------------------------------------|
| Ship a `governance_check_template.py` that the skill stamps out, instead of having the skill write the checker freehand each time | A hand-written-each-time checker is untested, drifts in quality run-to-run, and can silently get the exit-code or drift-class logic wrong — exactly the kind of governance regression this feature exists to prevent. A bundled, type-checked, unit-tested template guarantees every emitted checker is correct by construction. | Freehand generation: rejected — no test guarantee, quality varies per session, defeats the "durable governance" goal. Embedding the checker logic in `mixpanel_headless` as a public method: rejected — it is a user-owned cron/CI artifact, not part of the library's query/CRUD surface; shipping it as a template keeps the library lean and the artifact self-contained. |
| Put the keep/hide taste in a `references/governance-taste.md` with worked examples rather than inline in `SKILL.md` | The taste is the load-bearing judgment of the whole skill and is long (worked examples for coverage-vs-noise, granularity discrimination, sparse-but-valuable). Inlining it would blow the `SKILL.md` context budget and violate the progressive-disclosure house style. | Inline in SKILL.md: rejected — too long, violates Context Window Efficiency and the terse-SKILL.md convention. Omit the worked examples: rejected — the nuances (high coverage ≠ keep, low coverage ≠ hide) are precisely where naive classification fails. |
