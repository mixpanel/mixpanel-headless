# Bug report: `ShowClause` `oneOf` is ambiguous when `type` is omitted (FormulaShowClause / BehaviorShowClause)

**Repo**: `analytics` (Mixpanel webapp monorepo)
**Artifact**: `lib/common/mxpnl/report/bookmarks/generated/bookmark.json` (generated JSON Schema for `InsightsBookmarkParams`)
**Generator**: `lib/common/mxpnl/report/bookmarks/tools/generate_schema.py:21-27` — Pydantic v2 `InsightsBookmarkParams.model_json_schema(...)`, then `npx json2ts` → `iron/common/types/reports/bookmark.ts` via `tools/generate_schema.sh`
**Filed by**: mixpanel-headless TypeScript-port verification work (Phase 1), 2026-08-14. Discovered while building a conformance referee that validates builder-emitted bookmark payloads against this schema.
**Status**: local report only — not yet raised with analytics owners.

## Symptom

`ShowClause` is defined as:

```
ShowClause = oneOf [ FormulaShowClause, WarehouseShowClause, BehaviorShowClause ]
```

The branches are discriminated informally by `properties.type.const`:

| Branch | `type` const | `type` required? |
|---|---|---|
| `WarehouseShowClause` | `"warehouse"` | yes (`type` in `required`) |
| `BehaviorShowClause` | `"metric"` | **no** (default null) |
| `FormulaShowClause` | **none** | **no** |

Because `type` is optional on the Behavior and Formula branches, and `FormulaShowClause`
additionally has no `const` (and no required keys that would disambiguate it), a show
clause that omits `type` can validate against **more than one** branch. Under `oneOf`
semantics this is a validation **failure** ("valid under more than one schema") even for
payloads that are semantically valid and accepted by the server.

Minimal repro: a metric-shaped show clause without an explicit `"type"` key fails
schema validation with a `oneOf` multi-match error against
`Draft202012Validator` (Python `jsonschema`) and ajv `Ajv2020` alike.

## Root cause

The Pydantic source models declare the `type` discriminator as optional with a null
default on the Behavior/Formula branches, so `model_json_schema()` emits neither
`required: ["type"]` nor (for Formula) a `const`. The schema has no
`discriminator` keyword anywhere (grep: 302 `anyOf`, 2 `oneOf`, 0 `discriminator`),
so `oneOf` exclusivity is the only disambiguation mechanism — and it is not satisfiable
for `type`-less clauses.

## Impact

- Any consumer using `bookmark.json` as a validator must adopt an
  always-emit-`type` convention to avoid false rejections. (The mixpanel-headless
  conformance referee does exactly this: every generated show-clause fixture explicitly
  sets `"type": "metric"` / `"type": "formula"`.)
- The generated `bookmark.ts` union inherits the same ambiguity for structural typing.

## Suggested fix (either resolves it)

1. In the Pydantic models: make `type` a required `Literal` on all three branches
   (`"formula"` for `FormulaShowClause`), so the generated schema carries
   `const` + `required` per branch; or
2. Switch `ShowClause` to a Pydantic discriminated union on `type`, which emits an
   OpenAPI-style `discriminator` plus unambiguous branches.

Evidence gathered at analytics checkout state of 2026-08-14; details in
`context/phase1/recon/referee-assets.md` ("How report types are discriminated") of the
mixpanel-headless repo.
