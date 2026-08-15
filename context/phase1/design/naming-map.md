# Naming Map: snake_case <-> camelCase Policy (rulebook R7.6)

Status: FINAL for Phase 1. Companion to `phase1-design.md` (D12) and `vector.schema.json`.
Governing rules: R3.4 (wire keys stay snake_case; result fields are NOT camelized), R3.6 (input DTO casing), R7.3 (facade method naming), R7.6 (identifier casing + the mandate for this document), R10.11/R10.12 (number rendering, orthogonal but referenced).

## 1. Principles

1. **Vectors are Python-shaped.** Every key recorded in a vector is EXACTLY what Python emitted or accepted — the recorder never renames anything. All mapping happens in ONE place: the TS runner's boundary (loader/codecs/api-map), so there is exactly one implementation of the mapping to audit.
2. **The wire is sacred.** Anything that crosses HTTP (query params, JSON bodies, headers) or is a serialized artifact (bookmark JSON, selector strings, `details` bags, result fields) keeps its Python/API spelling in BOTH languages (R3.4, R7.6 exception clause). The TS library must EMIT these snake_case / API-spelled keys natively; there is nothing to map at compare time.
3. **Only identifiers map.** The mechanical snake→camel transform applies solely to (a) the method segment of `call.api` and (b) keyword-argument NAMES in `call.input` that correspond to pure argument bags (R3.6 camelCase side). Values are never transformed.

## 2. Key domains and their casing

| Domain | Vector spelling | TS runtime spelling | Mapping applied by |
|---|---|---|---|
| `call.api` module + method (`workspace.build_funnel_params`) | Python dotted snake_case | `workspace.buildFunnelParams` etc. | TS api-map (§5) |
| `call.input` kwarg names for facade/service methods (`from_date`, `conversion_window_unit`) | snake_case (as Python signature) | camelCase options keys (`fromDate`) per R3.3/R3.6 | TS codec: mechanical §3 transform + exceptions table |
| `call.input` kwarg names that ARE wire-shaped DTO fields (CRUD params models, e.g. `user_id`; R3.6) | snake_case | snake_case (kept — wire-shaped param models keep API field names) | none — exceptions table marks these `keep` |
| `$type`-tagged dataclass fields inside input values (`Filter.operator`, `FunnelStep.event`) | Python field names | TS type fields use the SAME names where the type is wire-adjacent; where the API map renames, the codec table owns it per-type | TS codecs.ts per-type field map (generated with the type, defaults to `keep`) |
| `expect.output` / `expect.result` keys (builder outputs, result-type shapes) | Python emission verbatim (`date_range`, `displayOptions`, `filter_by_cohort`, `legend_size`) | IDENTICAL — R3.4: "Result objects preserve exact Python result field names — do NOT camelize"; note the Mixpanel APIs themselves mix cases (`displayOptions` is camel ON THE WIRE; `date_range` is snake) — this is exactly why no transform may ever run on these | none (byte-identical requirement) |
| `expect.interactions[].request.params` / `json_body` keys | wire spelling verbatim (`from_date`, `fromDate` — the Query API itself is inconsistent, e.g. annotations use `fromDate`) | identical | none |
| Headers | lowercase (D5.3) | lowercased before compare | both canonicalizers |
| `expect.error` fields (`class`, `code`, `path`, `severity`) + code values (`V7_LAST_POSITIVE`, `U1`) | as-is | as-is — codes are the cross-language contract (R5.3); U/UP codes stay bare (`"U1"`), never "normalized" | none |
| Session fields (`project_id`, `workspace_id`) | snake_case | codec maps to the TS Session constructor's camelCase params (`projectId`) — but any serialized session artifact keeps snake | TS codec |
| Manifest / bundle metadata | snake_case (Python repo artifact) | read-only | none |

## 3. The mechanical mapping algorithm

For a name in the "maps" domains only:

```
snakeToCamel(name):
  segments = name.split("_")            # empty segments preserved: "__x" is never expected; assert no empty segment
  return segments[0] + segments[1:].map(capitalizeFirst).join("")
```

- Digits stay attached to their segment: `r2_score` → `r2Score`; `sha256_hash` → `sha256Hash`.
- No acronym special-casing: `url_normalizer` → `urlNormalizer`, `data_group_id` → `dataGroupId`, `id` → `id`. (Matches the api-map generator's behavior; acronyms are NOT uppercased — `apiClient`, not `APIClient` — per iron/house style.)
- The transform is applied to the FINAL segment of `call.api` (method/function name) and to top-level kwarg names per the DOMAIN-DEFAULT rule, which is machine-decidable without per-kwarg flags: a kwarg whose VALUE is a `$type`-tagged wire-shaped model (CRUD `*Params`, `Filter`, etc. — §2 rows 3-4) is `keep` (the codec owns its fields); every other kwarg (pure argument bags: scalars, lists, plain dicts, dates) defaults to mechanical camel per R3.6. Per-kwarg overrides, where ever needed, are explicit §4 rows with scope `kwarg:<api>` — there is no separate "domain defaults" flag store; the §4 row format `{python, ts, scope, rule}` plus this rule is the complete machine-readable source.
- The reverse transform (camelToSnake) is never needed at runtime — comparison always happens in Python-shaped space (the TS runner canonicalizes its OUTPUT, which per §2 rows 5-6 must already be Python-spelled).

## 4. Exceptions table

Maintained at `conformance-runner/src/naming-exceptions.json` (generated seed + hand additions, committed). Row format: `{"python": ..., "ts": ..., "scope": "api"|"kwarg:<api>"|"type:<TypeName>", "rule": "rename"|"keep"}`. Known seed rows:

| python | ts | scope | rule / reason |
|---|---|---|---|
| `workspace.build_params` | `workspace.buildParams` | api | mechanical (listed because it is the flagship; api-map.json is authoritative per WORKSPACE member NAME/params/kwonly — its `ts_signature` strings are NON-NORMATIVE sketches (Python generics, snake names like `async list_workspaces(): Promise<list[PublicWorkspace]>`) and the generator must not consume them, R7.3; NON-Workspace members resolve via the corpus `api-index.json` sidecar, phase1-design D4.4/D12) |
| module `segfilter.build_segfilter_entry` | `core/query/segfilter.buildSegfilterEntry` | api | module relocation per plan §4.1 (`src/query/`) |
| module `bookmark_builders.*` | `core/bookmarks/builders.*` (camelized fn names) | api | module relocation |
| module `query.user_builders.filter_to_selector` | `core/query/user-builders.filterToSelector` | api | relocation + mechanical |
| module `expressions.normalize_on_expression` | `core/query/expressions.normalizeOnExpression` | api | mechanical |
| module `transforms.transform_event` | `core/services/transforms.transformEvent` | api | mechanical |
| `compat.zfill` / `compat.python_str` / `compat.python_float_str` | `core/compat.zfill` / `pythonStr` / `pythonFloatStr` | api | R11.x canonical names |
| kwarg `where` (Filter\|str) everywhere | `where` | kwarg:* | keep (single word) |
| CRUD `*Params` model fields (e.g. `user_id`, `bookmark_id`) | same | type:* | keep — R3.6 wire-shaped DTOs |
| `Filter` fields (`prop`, `operator`, `value`, `prop_type`, `datetime_unit`, ...) | keep as generated with the type | type:Filter | codec-owned; default keep, api-map/type-gen may rename — any rename MUST add a row here before TS-4 lands |
| Python `_`-prefixed privates in `call.api` (none expected; registry uses public names + `_scan_custom_properties`, `_sanitize_raw_cohort`, `_iter_jsonl_lines`) | drop the underscore: `scanCustomProperties`, `sanitizeRawCohort`, `iterJsonlLines` | api | R7.6: "Python `_`-prefixed module-privates drop the underscore; privacy = not exported" — exported from an `/** @internal */` surface (R2.8) |

Unlisted names in mapping domains use the mechanical §3 transform; unlisted names in non-mapping domains are byte-identical. The TS runner FAILS FAST (`UNMAPPED_API` verdict) on any `call.api` in NEITHER api-map.gen.ts's sources (api-map.json workspace members, corpus `api-index.json`, this table) — silent fuzzy matching is forbidden; names whose MODULE is known from `api-index.json` but whose TS target is not yet built classify `UNPORTED`, not `UNMAPPED_API` (phase1-design D12).

## 5. How vectors carry naming metadata and how the TS runner applies it

- Vectors carry NO per-key naming metadata (principle 1: they are pure Python-shaped data). The policy artifacts are: this document (normative), `context/typescript-port-api-map.json` (per-member authority for WORKSPACE facade names, R7.3; committed per phase1-design D16), the corpus `api-index.json` sidecar (authority for every non-Workspace `call.api` + its positional/kw-only signature shape, phase1-design D4.4), and `naming-exceptions.json` (machine-readable deltas).
- TS runner pipeline per vector:
  1. Resolve `call.api` → TS callable via `api-map.gen.ts` (generated from api-map.json + api-index.json + §4 table). Unresolvable → `UNMAPPED_API` (fail) or `UNPORTED` (module known per api-index, not yet built).
  2. Decode `call.input`: for each kwarg, apply the domain rule (mechanical camel, or `keep` per exceptions); decode `$type` tags via `codecs.ts` per-type field maps.
  3. Invoke; take the RAW output (TS output is required by R3.4 to already use Python/API spellings for all serialized keys).
  4. Canonicalize (D6) and diff against `expect.*` — no naming transform on this side; any casing mismatch is a REAL conformance failure of the TS serializer, by design.
- Consequence worth stating loudly: if a TS builder emits `dateRange` where Python emits `date_range`, the vector fails — correct and intended. The naming map exists to translate the CALLING convention, never the OUTPUT.
