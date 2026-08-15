# Referee-Asset Recon (Phase 1)

Date: 2026-08-14. All paths under `/Users/jaredmcfarland/Developer/analytics` are READ-ONLY reference; every probe below ran from `/tmp` with `uv run --no-project --with <dep>` isolation. No writes, no installs into the analytics repo.

Mission scope note: mutation testing is out of scope (user directive 2026-08-14); nothing below depends on mutmut/StrykerJS.

---

## 1. Generated insights bookmark schema — `lib/common/mxpnl/report/bookmarks/generated/bookmark.json`

### Facts

| Property | Value | Evidence |
|---|---|---|
| Size | 164,126 bytes | `wc -c` |
| `$schema` | **absent** (no draft declared) | top-level keys = `additionalProperties, properties, required, title, type, definitions` |
| Effective draft | **2020-12 semantics required** — contains `prefixItems` (1 site: `checkpoints` tuple `[string, number]`) and `const` (6 sites) | grep counts: `prefixItems`=1, `const`=6, `$defs`=0, `definitions`=1, `if/then/else`=0, `patternProperties`=0 |
| Title / scope | `InsightsBookmarkParams` — **insights-only**, not a multi-report union | root `title` |
| Root type | `object`, `additionalProperties: false`, `required: ["displayOptions", "sections"]` | root keys |
| Root properties (11) | `columnWidths, displayOptions, forecastComparison, legend, liftComparison, name, sections, sorting, timeComparison, versions, executedMigrations` | |
| Definitions | 93 under `definitions` (NOT `$defs`), refs are `#/definitions/{name}`, all 91 used refs resolve | scripted check: `missing defs: []` |
| Strictness | `additionalProperties: false` at 44 sites, `true` at 5; 302 `anyOf`, 2 `oneOf` (`ShowClause`, `Statsig`), 0 `allOf`, 0 `discriminator` | grep counts |
| Permissive escape hatch | `definitions.JsonValue == {}` (matches anything); used for `sections.time` items, `Behavior.filters`, `BehaviorMeasurement.property`, etc. | |
| Nonstandard keyword | `"tsType"` appears 11× (e.g. `"tsType": "TopLevelMetricType.Metric"`) — a json2ts extension, not JSON-Schema | grep |
| Provenance | Pydantic v2 `InsightsBookmarkParams.model_json_schema(schema_generator=JsonSchemaGenerator, ref_template="#/definitions/{model}")` in `lib/common/mxpnl/report/bookmarks/tools/generate_schema.py:21-27`; then `npx json2ts generated/bookmark.json … iron/common/types/reports/bookmark.ts` via `tools/generate_schema.sh` | file reads |

### How report types are discriminated

There is **no report-type discriminator at the root** — this file only models insights bookmarks. The only union discrimination is inside `ShowClause`:

- `ShowClause` = `oneOf [FormulaShowClause, WarehouseShowClause, BehaviorShowClause]`
- Discriminated informally by `properties.type.const`: `WarehouseShowClause.type const = "warehouse"` (and `type` is in its `required`), `BehaviorShowClause.type const = "metric"` (**not required**, default null), `FormulaShowClause` has no const.
- **Gotcha for corpus vectors**: because `type` is optional on the Behavior/Formula branches, a show clause that omits `type` can match >1 branch and fail `oneOf` ("valid under more than one schema"). Always emit `"type": "metric"` / `"type": "formula"` in generated fixtures.
- Funnels/retention report params are covered elsewhere: draft-04 hand-written schemas in `bookmark_parser/{common,funnels}/schema/` (see §2), and `ChartType` enum in this file spans all report chart types (`funnel-steps`, `retention-curve`, …).

### Validator plugin requirements

- **Python `jsonschema`**: works out of the box, but because `$schema` is absent you must pin `Draft202012Validator` explicitly (default draft inference otherwise picks latest — same result today, but pin it for determinism). No RefResolver needed (all refs internal). `tsType` is ignored silently.
- **TS `ajv`**: must use `new Ajv2020()` (from `ajv/dist/2020`) — plain `Ajv` (draft-07) silently ignores `prefixItems`, weakening the `checkpoints` tuple check. Must either run `strict: false` or register `tsType` (and `title: ""` empty-string titles are fine) — ajv strict mode throws `strict mode: unknown keyword: "tsType"`. No `$ref` plugins needed; no format strings used.

### Transcript — validate a minimal insights payload (Python jsonschema)

```
$ cd /tmp && uv run --no-project --with jsonschema python - <<'EOF'
import json, jsonschema
from jsonschema import Draft202012Validator
schema = json.load(open('/Users/jaredmcfarland/Developer/analytics/lib/common/mxpnl/report/bookmarks/generated/bookmark.json'))
payload = {
    "displayOptions": {"chartType": "line"},
    "sections": {
        "show": [
            {
                "type": "metric",
                "behavior": {"type": "event", "name": "Login"},
                "measurement": {"math": "total"},
            }
        ],
        "time": [{"dateRangeType": "in the last", "unit": "day", "window": {"unit": "day", "value": 30}}],
    },
}
v = Draft202012Validator(schema)
errs = list(v.iter_errors(payload))
print("valid:", not errs)
bad = json.loads(json.dumps(payload)); bad["displayOptions"]["chartType"] = "nonsense-chart"
errs2 = list(v.iter_errors(bad))
print("negative control fails as expected:", bool(errs2), errs2[0].message[:80] if errs2 else "")
bad2 = json.loads(json.dumps(payload)); bad2["surprise"] = 1
print("extra-root-key rejected:", bool(list(v.iter_errors(bad2))))
EOF
jsonschema version: 4.26.0
valid: True
negative control fails as expected: True 'nonsense-chart' is not one of ['bar', 'line', 'pie', 'bar-stacked', 'stacked-li
extra-root-key rejected: True
```

---

## 2. `bookmark_parser/` — package layout, entry points, import feasibility

### Layout

```
bookmark_parser/
├── __init__.py                 # empty (0 bytes)
├── README.md                   # warning: bookmarks change often; only webapp & query-api should parse them
├── validate.py                 # THE standalone entry point (jsonschema, draft-04, custom file-$ref loader)
├── exceptions.py               # class BookmarkValidationError(Exception)
├── common/
│   ├── migrations/             # runner.py, hydrate_entities.py, types.py + funnels/ insights/ retention/ legacy-param migrations
│   ├── property_filter/  segfilter/  time_selector/  transforms/
│   └── schema/                 # draft-04 JSON schemas
│       ├── bookmark.json       # "common bookmark params across reports" (date_range, filter_by_event, filter_by_cohort, …)
│       ├── cohorts/cohort_selector.json (+ validate.py)
│       ├── property_selectors/{event_filter,user_filter,operator_expr,selector_expr}.json
│       └── time_selectors/time_selector.json
├── insights/
│   ├── validate.py             # voluptuous-based validate_insights_bookmark_params_schema(bookmark_params, require_all_keys=True)
│   ├── parser.py               # get_events_and_properties_queried_helper(...) etc. (deep analytics.* imports)
│   └── chart_utils.py, test_parser.py, test_validate.py
├── funnels/
│   ├── parser.py               # class FunnelBookmarkParser; .validate() -> assert_valid_schema(params, "funnels/schema/bookmark.json") [parser.py:320]
│   ├── validation.py           # voluptuous validate_funnels_query_params_schema(query_params)
│   └── schema/{bookmark.json (draft-04, allOf over common), top_paths_segments.json}
└── retention/parser.py         # class RetentionBookmarkParser
```

### Public entry points

1. **`bookmark_parser/validate.py` (standalone-safe; only third-party dep = `jsonschema`)**
   ```python
   def assert_valid_schema(data, schema_file):
       """Checks whether the given data matches the schema"""
       return validate(data, __load_json(schema_file))
   ```
   - `data`: dict payload; `schema_file`: path **relative to the bookmark_parser package dir** (e.g. `"common/schema/bookmark.json"`, `"funnels/schema/bookmark.json"`).
   - Returns `None` on success; raises `jsonschema.exceptions.ValidationError` on failure.
   - `__load_json` resolves `$ref` values as **package-relative file paths via a `json.load(..., object_hook=...)` hook, eagerly inlining them at load time** (validate.py lines 15-31). These are NOT standard JSON-pointer refs — TS/ajv would need a pre-bundling step (read each schema, recursively splice `{"$ref": "<relpath>.json"}` nodes) rather than an ajv ref resolver. A dict with `$ref` plus any other key raises `ValueError` ("there cannot be additional keys in a dict with $ref").
   - Schemas here declare `"$schema": "http://json-schema.org/draft-04/schema#"` (common/schema/bookmark.json line 2; funnels/schema/bookmark.json line 2) — Python jsonschema auto-selects Draft4Validator; ajv needs the `ajv-draft-04` package.
   - Self-recursion note baked into the schema: `"$comment": "self-recursive references seem to break the python jsonschema validator, so an extra level of depth was just hardcoded"` — filter trees deeper than 2 nested and/or groups are unvalidated.

2. **`bookmark_parser/insights/validate.py`** — `validate_insights_bookmark_params_schema(bookmark_params, require_all_keys=True)` (line 538). Voluptuous `Schema(...)(bookmark_params)`; returns `None`-ish (validated copy discarded, effectively raises-or-passes: observed return `NoneType`), raises `voluptuous.error.MultipleInvalid` on failure. Imports pull deep `analytics.*` modules (attribution → protobuf, time_utils → pandas/pytz).

3. **`bookmark_parser/funnels/parser.py`** — `FunnelBookmarkParser`; `.validate()` delegates to `assert_valid_schema(self.bookmark_params, "funnels/schema/bookmark.json")`.

### Third-party dependency sweep (from `grep -rE '^(import|from) …'` over all .py)

Direct third-party imports inside the package: `jsonschema` (2), `voluptuous` (4), `pytest` (9, tests only), `freezegun` (5, tests only), `pytz` (1), `prison` (1), `standalone` (1, internal bootstrap), plus stdlib. But most modules import `analytics.*` absolutes (27× `analytics.bookmark_parser.common.migrations.types`, plus `analytics.backend.util.*`, `analytics.api.version_2_0.*` …), which transitively require **protobuf** (generated `*_pb2.py`), **pandas**, **pytz**, **voluptuous**.

### Transcript A — bare import (mission's exact probe) + standalone validate

```
$ cd /tmp && PYTHONPATH=/Users/jaredmcfarland/Developer/analytics \
  uv run --no-project --with jsonschema python -c "
import bookmark_parser
print('import bookmark_parser OK, file =', bookmark_parser.__file__)
import bookmark_parser.validate as v
print('import bookmark_parser.validate OK')
import bookmark_parser.exceptions as e
print('exceptions:', e.BookmarkValidationError)
"
import bookmark_parser OK, file = /Users/jaredmcfarland/Developer/analytics/bookmark_parser/__init__.py
import bookmark_parser.validate OK
exceptions: <class 'bookmark_parser.exceptions.BookmarkValidationError'>
```

```
$ cd /tmp && PYTHONPATH=/Users/jaredmcfarland/Developer/analytics uv run --no-project --with jsonschema python - <<'EOF'
import json
from bookmark_parser.validate import assert_valid_schema
payload = {
    "date_range": {
        "type": "in the last",
        "from_date": {"unit": "day", "value": 30},
        "to_date": {"unit": "day", "value": 0},
        "window": {"unit": "day", "value": 30},
    }
}
print("assert_valid_schema OK:", assert_valid_schema(payload, "common/schema/bookmark.json"))
bad = json.loads(json.dumps(payload)); bad["date_range"]["window"]["unit"] = "fortnight"
try:
    assert_valid_schema(bad, "common/schema/bookmark.json")
    print("BAD payload passed (unexpected)")
except Exception as e:
    print("negative control raised:", type(e).__module__ + "." + type(e).__name__, str(e).split("\n")[0][:100])
EOF
assert_valid_schema OK: None
negative control raised: jsonschema.exceptions.ValidationError 'fortnight' is not one of ['minute', 'hour', 'day', 'week', 'month', 'year']
```

### Transcript B — deep insights validator (make-or-break item): WORKS with 4 extra wheels

Absolute `analytics.*` imports require `PYTHONPATH=/Users/jaredmcfarland/Developer` (parent of the repo; the repo root has an `__init__.py`, so the checkout itself is the `analytics` package).

Failure ladder observed (exact errors):
1. bare: `ModuleNotFoundError: No module named 'google'` (via `analytics/backend/util/behaviors/attribution.py:5` → `analytics.protobuf.backend.common.pb.over_time_params_pb2`) → add `protobuf`
2. `ModuleNotFoundError: No module named 'pandas'` (via `analytics/backend/util/time_utils/parser.py:1`) → add `pandas`
3. `ModuleNotFoundError: No module named 'pytz'` (via `analytics/backend/util/time_utils/project_time.py:8`; pandas 3.x no longer drags pytz in) → add `pytz`

```
$ cd /tmp && PYTHONPATH=/Users/jaredmcfarland/Developer \
  uv run --no-project --with voluptuous --with protobuf --with pandas --with pytz python -c "
from analytics.bookmark_parser.insights.validate import validate_insights_bookmark_params_schema
print('deep import OK')
payload = {
    'sections': {
        'show': [{'math': 'total', 'resourceType': 'events', 'value': {'name': 'Login', 'resourceType': 'events'}}],
        'time': [{'dateRangeType': 'in the last', 'unit': 'day', 'window': {'unit': 'day', 'value': 30}}],
    },
    'displayOptions': {'chartType': 'line', 'plotStyle': 'standard', 'analysis': 'linear', 'value': 'absolute'},
}
out = validate_insights_bookmark_params_schema(payload, require_all_keys=False)
print('validate_insights_bookmark_params_schema OK ->', type(out).__name__)
"
deep import OK
validate_insights_bookmark_params_schema OK -> NoneType
```

Negative-control probes (same env):

```
show-not-a-list -> raised MultipleInvalid : expected a list for dictionary value @ data['sections']['show']
bad-time-unit   -> raised MultipleInvalid : value must be one of ['day', 'hour', 'minute', 'month', 'quarter', 'week', 'year'] ...
bad-chartType   -> raised MultipleInvalid : value must be one of ['bar', 'column', 'frequency-curve', 'funnel-steps', ...
bad-math-strict -> PASSED        # {'math': 'NOT_A_MATH'} sneaks through: one Any(...) branch (multi-metric clause, ALLOW_EXTRA) accepts it
```

**Conclusion**: the deep voluptuous validator is usable as a differential oracle with exactly `PYTHONPATH=/Users/jaredmcfarland/Developer` + `--with voluptuous --with protobuf --with pandas --with pytz` (pin: voluptuous latest-at-run, protobuf 6.x wheel resolved by uv, pandas 3.x, pytz). It is structure-strict but **not** enum-strict on `math` (Any-branch looseness) — the referee should treat "both validators accept" / "both reject" as the oracle signal, not error-message equality. Note the two validators disagree on shape vocabulary: `insights/validate.py` expects the legacy flat show clause (`math`/`resourceType`/`value`), while `generated/bookmark.json` expects the modern nested clause (`behavior`/`measurement`); a corpus fixture set needs both dialects (migrations in `common/migrations/insights/legacy.py` convert between them).

---

## 3. schema4api + OpenAPI assets

### 3a. `webapp/app_api/**/types.d.ts` — count **45 confirmed** (`find … -name types.d.ts | wc -l` → 45)

Full list (relative to `webapp/app_api/`): `avatars`, `billing`, `billing_bump/detail_views/{account_deletion_workflows,project_entitlements}`, `embed`, `me`, `organizations/{audit_logs,domains,project_creation,sdk_settings,service_accounts,teams/service_accounts}`, `personal_access_tokens`, `product_updates`, `projects` (itself), `projects/{agent_flows, ai_skill, alerts/custom, audit_logs, banners, behaviors, bookmarks, connectors, dashboards, data_definitions, data_governance/magic_merge, data_groups, entitlements, events, experiments, feature_flags, heat_maps, integrations, integrations/realtime, metrics, playlists, presence, rca, replays, sdk_settings, sendbird, themes, warehouse_sources}`, `public`, `user_media`.

Entity coverage vs the mission's checklist: **dashboards YES, bookmarks YES, flags YES (`feature_flags`), alerts PARTIAL (`alerts/custom` only), lexicon YES-as `data_definitions`, replays YES, webhooks NO** (webhook types live in iron: `iron/common/types/schema4api/webapp/project_webhooks/types.d.ts`). Cohorts have no types.d.ts here.

Generation mechanism: each `types.d.ts` header says "automatically generated by the schema4api generator… run `npm run schema4api`". `package.json:43` → `"schema4api": "./iron/scripts/schema4api.sh"`, which (1) runs `lib/common/mxpnl/report/bookmarks/tools/generate_schema.sh` (regenerates the §1 bookmark.json + `iron/common/types/reports/bookmark.ts` via `json2ts`), then (2) `MP_ENV_TYPE=unit_test python ./webapp/schema4api/generate.py` — that script harvests draft-07 JSON schemas from `webapp/app_api/**/__types__/*.py` (see `webapp/app_api/schema.py`: emits `"$schema": "http://json-schema.org/draft-07/schema#"` response envelopes `{status: ok, results} | {status: error, error}`) and shells out to `node_modules/.bin/json2ts` + prettier. Pinned: `json-schema-to-typescript` **15.0.0** (`package.json:221`).

### 3b. `iron/common/types/schema4api/`

Layout: `admin-permissions.d.ts` + `webapp/` mirror tree (10 files): `webapp/{project_webhooks,user,github,reports,user/security/passkeys,user/security/totp_selfservice,admin/internal/analysis/canvases,admin/internal/product_platform/{staff_registry,manage_redis}}/types.d.ts`. Same generator, same header.

### 3c. `webapp/app_api/v1/generated/openapi.internal.json`

- 46,358 bytes; OpenAPI **3.1.0**; title "Mixpanel Platform API 1"; **only 7 paths**, 19 component schemas:
  `/v1/projects/{project_id}/event-definitions/{merge,unmerge}`, `/v1/projects/{project_id}/property-definitions/{merge,unmerge}`, `/v1/organizations/{organization_id}/audit-logs/query`, `/v1/organizations/{organization_id}/audit-log-streams`, `/v1/global-token-revocation`.
- **It does NOT cover dashboards/bookmarks/flags/alerts/replays/webhooks** — those stay on the legacy Django app_api surface whose only machine-readable contract is the 45 schema4api `types.d.ts` files (and the `__types__/*.py` schemas behind them).
- Provenance: generated from the live django-ninja `api` object by `webapp/app_api/v1/tools/generate_openapi.py` (requires `standalone.init(django=True)` — full Django boot; NOT runnable outside the analytics dev env), then redocly bundle/lint. `generated/README.md` documents `openapi.json` (419 B stub) as the public spec filtered by `redocly.yaml` `filter-in`.

### 3d. `api_references/openapi/src/common/*.yaml`

Tiny reusable-component stubs, not full specs: `app-api.yaml` (434 B — just the `https://{regionAndDomain}.com/api/app` server object), `export-api.yaml` (401 B — `https://{data|data-eu}.mixpanel.com/api/2.0` server), `ingestion-api.yaml` (2,485 B), plus `parameters/responses/schemas/securitySchemes.yaml`. `api_references/openapi/src/` otherwise contains only `data-definitions.internal.openapi.yaml`. Useless as an entity-CRUD contract source; useful only for canonical server URLs.

### 3e. hey-api pipeline evidence

- `package.json:150` — `"@hey-api/openapi-ts": "0.99.0"` (devDependency); `package.json:146` — `"openapi-ts:platform": "openapi-ts -f openapi-ts.platform.config.cjs"`.
- Repo-root `openapi-ts.platform.config.cjs`: input `webapp/app_api/v1/generated/openapi.internal.json`, output `iron/generated/platform/v1/` (exists: `types.gen.ts` 24,789 B, `sdk.gen.ts` 7,531 B, `client.gen.ts`, `@tanstack/`, `core/`), plugins `@hey-api/typescript`, `@hey-api/client-fetch` (runtimeConfigPath `./iron/common/util/platform-api`), `@hey-api/sdk`, `@tanstack/react-query`; postProcess prettier + a `return;`→`return undefined;` sed fixer.
- Orchestration: `justfile:364-377` — `generate-platform-openapi-spec` (Django-booted python generator + `npm run redocly:bundle:platform` + `redocly:lint:platform`, `@redocly/cli` 2.39.0) → `generate-platform-openapi-ts` (`npm run openapi-ts:platform`) → alias `platform-openapi`.

### 3f. Recommended regeneration recipe for the TS repo

Do NOT try to regenerate specs from the analytics repo (needs a full Django boot). Instead treat the two committed artifacts as vendored inputs and regenerate TS types only:

1. **Vendor inputs** (copy, with SHA + date, into `vendor/mixpanel-contracts/` in the TS repo):
   - `webapp/app_api/v1/generated/openapi.internal.json` (Platform v1: data-governance merge/unmerge, audit logs, token revocation)
   - `lib/common/mxpnl/report/bookmarks/generated/bookmark.json` (insights bookmark params)
   - the 45 `webapp/app_api/**/types.d.ts` + 10 `iron/common/types/schema4api/webapp/**/types.d.ts` (already TypeScript — vendor verbatim; regenerating them requires the Django env)
2. **Platform v1 client** (only if the port needs those 7 endpoints): `@hey-api/openapi-ts@0.99.0` pinned, config mirroring `openapi-ts.platform.config.cjs` but with plugins reduced to `@hey-api/typescript` (+ `@hey-api/client-fetch`/`@hey-api/sdk` if a runtime client is wanted; drop `@tanstack/react-query`); input = vendored `openapi.internal.json`; output `src/generated/platform/v1/`.
3. **Bookmark types**: `json-schema-to-typescript@15.0.0` pinned, same flags as `generate_schema.sh`: `json2ts vendor/mixpanel-contracts/bookmark.json src/generated/reports/bookmark.ts --no-enableConstEnums --no-unknownAny --unreachableDefinitions` (the `tsType` extension keys then take effect the same way they do for `iron/common/types/reports/bookmark.ts`).
4. **Runtime validation in the TS referee**: `ajv@8` with `Ajv2020` + `strict: false` (or `keywords: ["tsType"]`) for the generated bookmark schema; `ajv-draft-04` + a pre-bundling splice step (mirror `bookmark_parser/validate.py.__object_hook_dereference`) for the draft-04 `bookmark_parser/**/schema/*.json` files.
5. Freshness check in CI: byte-compare vendored copies against the analytics checkout (read-only diff), fail with "re-vendor" message on drift.

---

## Referee-harness readiness summary

| Harness | Oracle | Status | Invocation |
|---|---|---|---|
| Insights-bookmark schema referee | `generated/bookmark.json` + jsonschema `Draft202012Validator` / ajv `Ajv2020` | **proven** (§1 transcript, pos+2 neg controls) | `uv run --no-project --with jsonschema` from /tmp |
| bookmark_parser structural referee | `bookmark_parser.validate.assert_valid_schema` (draft-04, file-refs) | **proven** (§2 transcript A) | `PYTHONPATH=/Users/jaredmcfarland/Developer/analytics uv run --no-project --with jsonschema` |
| bookmark_parser deep-validator referee | `analytics.bookmark_parser.insights.validate.validate_insights_bookmark_params_schema` | **proven with caveats** (§2 transcript B; enum-loose on `math`; legacy show-clause dialect) | `PYTHONPATH=/Users/jaredmcfarland/Developer uv run --no-project --with voluptuous --with protobuf --with pandas --with pytz` |
| App-API type referee | vendored types.d.ts + hey-api/json2ts regeneration | **recipe defined** (§3f); no OpenAPI for entity CRUD exists — types.d.ts are the only contract | n/a (compile-time) |
