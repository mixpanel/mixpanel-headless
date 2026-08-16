# Bug report: `build_group_section` threads an `int` `data_group_id` verbatim into clause-level `dataGroupId`, which the analytics bookmark contract types `string | null`

**Repo**: `mixpanel-headless` (this repo)
**Artifact**: `src/mixpanel_headless/_internal/bookmark_builders.py` — `build_group_section`
(`data_group_id: int | None = None`, line 250; emitted verbatim at `:317`, `:344`, `:461`
[cohort entries via `_build_cohort_group_entry` `:441` `data_group_id` + `:461` `dataGroupId`],
and `:794` [frequency entries via `build_frequency_group_entry` `:743`]). Reachable via
`Workspace.build_params(..., group_by=..., data_group_id=...)` and the query facade paths
that thread `data_group_id`.
**Filed by**: TypeScript-port B3 batch gate (referee (a) runner feed, first run of the D15a
insights-shaped feed over `build_group_section` outputs), 2026-08-15.
**Status**: OPEN — R10.7: reported, NOT fixed in the Phase-3 workflow. A fix is a Python-first
TDD cycle + conformance-vector re-extraction (the corpus records the current int-valued shape);
until that cycle lands, the TS port replicates the int threading byte-for-byte.

## Symptom

The B3-gate ajv referee (vendored `bookmark.json`, generated from the analytics TS report
types) REJECTs 4 corpus payloads, all `bookmark_builders.build_group_section` outputs whose
tests pass `data_group_id=5` (an `int`, matching the parameter annotation):

- `…testbuildgroupsectiondatagroupid-test_cohort_breakdown_group_with_data_group_id`
- `…testbuildgroupsectiondatagroupid-test_custom_property_ref_group_with_data_group_id`
- `…testbuildgroupsectiondatagroupid-test_inline_custom_property_group_with_data_group_id`
- `…testbuildgroupsectionfrequency-test_data_group_id_threaded_to_frequency`

Error (representative): `/sections/group/0/dataGroupId: must be string; must be null;
must match a schema in anyOf`.

## Evidence that the contract is `string | null`

Two INDEPENDENT analytics oracles agree on the clause-level spelling:

1. Vendored draft-2020-12 `bookmark.json` (generated from the analytics report TS types):
   `DataGroupId = {"anyOf": [{"type": "string"}, {"type": "null"}]}`; `GroupClause.dataGroupId`
   and `Sections.globalDataGroupId` both `$ref` it.
2. The deep voluptuous validator (`analytics/bookmark_parser/insights/validate.py:222,263,301,368`):
   `Optional("dataGroupId"): Any(None, str)` at every CLAUSE level. (Contrast `:312,338`:
   the RAW-cohort interior `data_group_id` is `Any(int, str, None)` — the int form is legal
   only inside `raw_cohort` payloads, which is exactly where the library's saved-cohort
   entries do NOT put the threaded value.)

No live probe was run (Phase 3 runs nothing against live Mixpanel, P3-7); whether the query
engine coerces int→str server-side is unverified. The finding stands as a typed-contract
mismatch regardless: the library's own annotation (`int | None`) steers callers into emitting
a shape both analytics validators reject.

## Why the deep referee (b) never caught it

The referee-(b) handoff feeds only `workspace.build_params` / `build_time_section` /
`build_date_range` payloads to the deep oracle; no corpus `build_params` vector threads
`data_group_id` into a group clause. The B3-gate ajv feed is the first oracle to see
`build_group_section` outputs — its `sections.group` slot is the one schema-constrained
slot (`GroupClause`, `additionalProperties: false`).

## Suggested fix (Python-first, out of scope here)

Either annotate `data_group_id: str | int | None` and coerce to `str` at emission, or keep
`int | None` and emit `str(data_group_id)` — probe the live App API first to confirm which
spelling saved bookmarks actually store. Then re-extract vectors, re-pin, and port the fix.

## Standing disposition (until fixed)

The 4 ajv REJECTs are expected-and-disclosed, pinned exactly in
`differential/test/bookmark-referee-feed.test.ts` (TS repo) the same way referee (b) carries
its 2 frequency-filter REJECTs — new rejects beyond the pinned set still block.
